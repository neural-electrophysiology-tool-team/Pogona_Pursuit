import deeplabcut
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import cv2
import re
from pose import Analyzer, BODY_PARTS
from loader import Loader

NUM_FRAMES_BACK = 60 * 5


class StrikesAnalyzer:
    def __init__(self, loader: Loader = None, experiment_name=None, trial_id=None, camera=None):
        self.loader = loader or Loader(experiment_name, trial_id, camera)
        self.pose_analyzer = Analyzer(self.loader.video_path)
        self.xfs = []

    def get_strikes_pose(self, n_frames_back=None):
        """Run pose estimation on hits frames"""
        n_frames_back = n_frames_back or NUM_FRAMES_BACK

        def first_frame(frame_id):
            return frame_id - n_frames_back if frame_id >= n_frames_back else 0

        frames_groups = [list(range(first_frame(f), f + 1)) for f in self.loader.get_hits_frames()]
        return self.get_pose_estimation(frames_groups)

    def get_pose_estimation(self, frames: list):
        flat_frames = sorted([item for sublist in frames for item in sublist])
        res_df = self.pose_analyzer.run_pose(flat_frames, is_save_frames=True)
        for frame_group in frames:
            self.xfs.append(res_df.loc[frame_group, :])
        return self.xfs

    def play_strike(self, xf: pd.DataFrame, n=20):
        frames2plot = xf.index[-n:]
        cols = 3
        rows = int(np.ceil(len(frames2plot) / cols))
        fig, axes = plt.subplots(rows, cols, figsize=(20, 5 * rows))
        axes = axes.flatten()
        for i, frame_id in enumerate(frames2plot):
            frame = self.pose_analyzer.saved_frames.get(frame_id)
            if frame is None:
                continue
            axes[i].imshow(frame, aspect="auto")
            for part in BODY_PARTS:
                axes[i].scatter(xf.loc[frame_id, part].x, xf.loc[frame_id, part].y)
            axes[i].set_title(frame_id)
        fig.tight_layout()
        plt.show()

    def ballistic_analysis(self):
        res = []
        hits_df = self.loader.hits_df
        for i, xf in enumerate(self.xfs):
            strike_start_time = self.loader.frames_ts[self.strike_start_index(xf)]
            traj_time = self.loader.traj_df.time.dt.tz_convert('utc').dt.tz_localize(None)
            closest_hit_index = (traj_time - pd.to_datetime(strike_start_time)).abs().argsort()[0]
            bug_start_pos = self.loader.traj_df.loc[closest_hit_index, :]
            PD = distance(bug_start_pos.x, hits_df.loc[i, 'x'], bug_start_pos.y, hits_df.loc[i, 'y'])
            MD = distance(hits_df.loc[i, 'bug_x'], hits_df.loc[i, 'x'],
                          hits_df.loc[i, 'bug_y'], hits_df.loc[i, 'y'])
            res.append(PD / MD)
        return res

    @staticmethod
    def strike_start_index(xf: pd.DataFrame, th=2.5):
        dy = xf['nose'].y.diff()
        return xf[dy > th].index[0]


def distance(x1, y1, x2, y2):
    return np.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)