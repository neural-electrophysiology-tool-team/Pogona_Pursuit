from datetime import datetime, timedelta
from flask import Flask, render_template, Response, request
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from dateutil import parser as date_parser

import config
from utils import to_integer

app = Flask(__name__)


@app.route('/')
def explore():
    return render_template('explore.html')


@app.route('/experiment_results', methods=['POST'])
def experiment_results():
    data = request.json
    ea = ExperimentAnalyzer(**data)
    df = ea.get_experiments()
    if len(df) < 1:
        return Response('No experiments found')
    return Response(df.to_html(classes='table-responsive'))


@dataclass
class ExperimentAnalyzer:
    start_date: datetime
    end_date: datetime
    bug_types: str = None
    animal_id: int = None
    movement_type: str = None
    num_of_strikes: int = 0
    experiment_dir: str = field(default=config.explore_experiment_dir)

    def __post_init__(self):
        if isinstance(self.start_date, str):
            self.start_date = date_parser.parse(self.start_date)
        if isinstance(self.end_date, str):
            self.end_date = date_parser.parse(self.end_date + 'T23:59')

    def get_experiments(self) -> pd.DataFrame:
        res_df = []
        print(f'experiments folder: {self.experiment_dir}')
        for exp_path in Path(self.experiment_dir).glob('*'):
            try:
                info_path = exp_path / 'experiment.log'
                if not info_path.exists() or not self.is_in_date_range(exp_path):
                    continue
                info = self.get_experiment_info(info_path)
                if not self.is_match_conditions(info):
                    continue
                trial_data = self.get_trials_data(exp_path, info)
                res_df.append(trial_data)
            except Exception as exc:
                print(f'Error loading {exp_path.name}; {exc}')

        if len(res_df) > 0:
            res_df = pd.concat(res_df)
            res_df.rename(columns={'name': 'experiment'}, inplace=True)
            res_df = self.group_by_experiment_and_trial(res_df)
            res_df = self.filter_trials_by_metric(res_df)

        return res_df

    def get_trials_data(self, exp_path: Path, info: dict) -> pd.DataFrame:
        trials = []
        for trial_path in exp_path.glob('trial*'):
            trial_df = self.get_screen_touches(trial_path)
            trial_meta = dict()
            trial_meta['trial'] = int(re.match(r'trial(\d+)', trial_path.stem)[1])
            trial_meta['trial_start'] = self.get_trial_start(trial_path, info, trial_meta['trial'])
            for k, v in trial_meta.items():
                trial_df[k] = v if len(trial_df) > 1 else [v]
            trials.append(trial_df)

        trials = pd.concat(trials)
        for key, value in info.items():
            trials[key] = value

        return trials

    @staticmethod
    def get_screen_touches(trial_path: Path) -> pd.DataFrame:
        res = pd.DataFrame()
        touches_path = trial_path / 'screen_touches.csv'
        if touches_path.exists():
            res = pd.read_csv(touches_path, parse_dates=['time'], index_col=0).reset_index(drop=True)
        return res

    def get_trial_start(self, trial_path: Path, info: dict, trial_id: int) -> (datetime, None):
        """Get start time for a trial based on trajectory csv's first record or if not exists, based on calculating
        trial start using meta data such as trial_duration, ITI, etc.."""
        def _calculate_trial_start_from_meta():
            extra_time_recording = info.get('extra_time_recording') or config.extra_time_recording
            time2trials = info['trial_duration'] * (trial_id - 1) + info['iti'] * (trial_id - 1) + \
                          extra_time_recording * trial_id + extra_time_recording * (trial_id - 1)
            exp_time = self.get_experiment_time(info)
            return exp_time + timedelta(seconds=time2trials)

        traj_path = trial_path / 'bug_trajectory.csv'
        if not traj_path.exists():
            return _calculate_trial_start_from_meta()

        res = pd.read_csv(traj_path, parse_dates=['time'], index_col=0).reset_index(drop=True)
        if len(res) < 1:
            return _calculate_trial_start_from_meta()
        return res['time'][0]

    @staticmethod
    def group_by_experiment_and_trial(res_df: pd.DataFrame) -> pd.DataFrame:
        group = lambda x: x.groupby(['experiment', 'trial'])
        to_percent = lambda x: (x.fillna(0) * 100).map('{:.1f}%'.format)
        exp_group = group(res_df)
        exp_df = exp_group[['animal_id']].first()

        num_strikes = exp_group['is_hit'].count()
        exp_df['num_of_strikes'] = num_strikes
        exp_df['strike_accuracy'] = to_percent(group(res_df.query('is_hit==1'))['is_hit'].count() / num_strikes)
        exp_df['reward_accuracy'] = to_percent(
            group(res_df.query('is_reward_bug==1'))['is_reward_bug'].count() / num_strikes)

        first_strikes_times = remove_tz(exp_group['time'].first())
        exp_df['trial_start'] = remove_tz(exp_group['trial_start'].first())
        exp_df['time_to_first_strike'] = (first_strikes_times - exp_df['trial_start']).astype('timedelta64[s]')
        exp_df['trial_start'] = localize_dt(exp_df['trial_start'])

        META_COLS = ['bug_speed', 'movement_type', 'bug_types']
        exp_cols = [x for x in META_COLS if x in res_df.columns]
        exp_df = pd.concat([exp_df, exp_group[exp_cols].first()], axis=1)
        exp_df = exp_df.sort_values(by=['trial_start', 'trial'])
        exp_df.drop(columns=['num_trials', 'exp_time'], inplace=True, errors='ignore')

        return exp_df

    def filter_trials_by_metric(self, res_df):
        metrics = ['num_of_strikes']
        for metric in metrics:
            res_df = res_df.query(f'{metric} >= {getattr(self, metric)}')

        return res_df

    def is_in_date_range(self, exp_path):
        try:
            exp_date = str(exp_path).split('_')[-1]
            exp_date = date_parser.parse(exp_date)
            return self.start_date <= exp_date <= self.end_date
        except Exception as exc:
            print(f'Error parsing experiment {exp_path}; {exc}')

    @staticmethod
    def get_experiment_time(info: dict) -> datetime:
        return date_parser.parse(info.get('name').split('_')[-1])

    def is_match_conditions(self, info):
        attrs2check = ['bug_types', 'animal_id', 'movement_type']
        for attr in attrs2check:
            req_value = getattr(self, attr)
            if not req_value:
                continue
            info_value = info.get(attr)
            if not info_value or \
                    (isinstance(req_value, (int, float)) and req_value != to_integer(info_value)) or \
                    (isinstance(req_value, str) and req_value not in info_value):
                return False
        return True

    @staticmethod
    def get_experiment_info(p: Path):
        """Load the experiment info file to data frame"""
        info = {}
        int_fields = ['iti', 'trial_duration', 'animal_id', 'extra_time_recording']
        with p.open('r') as f:
            m = re.finditer(r'(?P<key>\w+): (?P<value>\S+)', f.read())
            for r in m:
                key = r.groupdict()['key'].lower()
                value = r.groupdict()['value']
                if key in int_fields:
                    value = to_integer(value)
                info[key] = value
        return info


def remove_tz(col):
    return pd.to_datetime(col, utc=True).dt.tz_convert('utc').dt.tz_localize(None)


def localize_dt(col: pd.Series):
    return col.dt.tz_localize('utc').dt.tz_convert('Asia/Jerusalem').dt.strftime('%Y-%m-%d %H:%M:%S')
