import re
from pathlib import Path
import pandas as pd

import sys
sys.path += ['../Arena']
from explore import ExperimentAnalyzer

ROOT_DIR = '/data'
EXPERIMENTS_DIR = ROOT_DIR + '/Pogona_Pursuit/Arena/experiments'
CAMERAS = {
    'realtime': '19506468',
    'right': '19506475',
    'left': '19506455',
    'back': '19506481',
}


class Loader:
    def __init__(self, experiment_name=None, trial_id=None, camera=None, video_path=None):
        if video_path:
            video_path = Path(video_path)
            experiment_name, trial_id, camera = self.parse_video_path(video_path)
        self.experiment_name = experiment_name
        self.trial_id = trial_id
        self.camera = camera
        self.video_path = video_path or self.get_video_path()

        self.frames_ts = self.get_frames_timestamps()
        self.hits_df = self.get_hits()
        self.traj_df = self.get_bug_trajectory()

    def get_hits(self, hits_only=False):
        df = pd.read_csv(self.screen_touches_path, index_col=0, parse_dates=['time']).reset_index(drop=True)
        if hits_only:
            df = df.query('is_hit == 1')
        return df

    def get_bug_trajectory(self):
        try:
            return pd.read_csv(self.bug_traj_path, index_col=0, parse_dates=['time']).reset_index(drop=True)
        except Exception as exc:
            raise Exception(f'Error loading bug trajectory; {exc}')

    def get_frames_timestamps(self):
        return pd.read_csv(self.timestamps_path, index_col=0).reset_index(drop=True)['0']

    def get_hits_frames(self):
        """return the frame ids for screen strikes"""
        frames = []
        for hit_ts in self.hits_df['time'].dt.tz_convert('utc').dt.tz_localize(None):
            frames.append(closest_index(self.frames_ts, hit_ts))
        return frames

    def get_bug_position_at_time(self, t) -> pd.DataFrame:
        return self.traj_df.loc[closest_index(self.traj_df['time'], t), ['x', 'y']]

    def bug_data_for_frame(self, frame_id: int) -> pd.DataFrame:
        frame_time = self.frames_ts[frame_id]
        return self.traj_df.loc[closest_index(self.traj_df['time'], frame_time), :]

    def validate(self):
        assert self.experiment_path.exists(), 'experiment dir not exist'
        assert self.trial_path.exists(), 'no trial dir'
        assert self.bug_traj_path.exists(), 'no bug trajectory file'
        assert self.screen_touches_path.exists(), 'no screen touches file'
        assert self.video_path.exists(), 'no video file'
        assert self.timestamps_path.exists(), 'no timestamps file'

    @staticmethod
    def parse_video_path(video_path: Path):
        assert video_path.exists(), f'provided video path: {video_path} does not exist'
        try:
            experiment_name = video_path.parts[-4]
            trial_id = int(video_path.parts[-3].split('trial')[1])
            camera = None
            for name, serial in CAMERAS.items():
                if name in video_path.name or serial in video_path.name:
                    camera = name
                    break
            if not camera:
                raise Exception('unable to parse camera from video path')
            return experiment_name, trial_id, camera
        except Exception as exc:
            raise Exception(f'Error parsing video path: {exc}')

    def get_video_path(self) -> Path:
        assert isinstance(self.camera, str), 'no camera name provided or bad type'
        regex = self.camera + r'_\d{8}T\d{6}.(avi|mp4)'
        videos = [v for v in (self.trial_path / 'videos').glob('*') if re.match(regex, v.name)]
        if not videos:
            raise Exception('cannot find video')
        elif len(videos) > 1:
            raise Exception('found more than one video')
        return videos[0]

    @property
    def experiment_path(self):
        return EXPERIMENTS_DIR / Path(self.experiment_name)

    @property
    def trial_path(self):
        return self.experiment_path / f'trial{self.trial_id}'

    @property
    def bug_traj_path(self):
        return self.trial_path / f'bug_trajectory.csv'

    @property
    def screen_touches_path(self):
        return self.trial_path / f'screen_touches.csv'

    @property
    def timestamps_path(self):
        return self.trial_path / 'videos' / 'timestamps' / f'{CAMERAS[self.camera]}.csv'


def closest_index(series, x):
    return (series - x).abs().argsort()[0]


def get_experiments(*args, **kwargs):
    """Get experiment using explore"""
    df = ExperimentAnalyzer(*args, **kwargs).get_experiments()
    loaders = []
    for experiment, trial in df.index:
        try:
            ld = Loader(experiment, int(trial), 'realtime')
            loaders.append(ld)
        except Exception as exc:
            continue
            # print(f'Error loading {experiment} trial{trial}; {exc}')
    print(f'num loaders: {len(loaders)}')
    return loaders
