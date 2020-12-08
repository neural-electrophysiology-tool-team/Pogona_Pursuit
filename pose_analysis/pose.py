from pathlib import Path
import pandas as pd
import numpy as np
import cv2
import yaml
from dlclive import DLCLive, Processor
from loader import Loader

DLC_PATH = '/data/pose_estimation/deeplabcut/projects/pogona_pursuit-regev-2020-07-19'
DLC_CONFIG_FILE = DLC_PATH + '/config.yaml'
EXPORTED_MODEL_PATH = DLC_PATH + '/exported-models/DLC_pogona_pursuit_resnet_50_iteration-1_shuffle-1'
PROBABILITY_THRESH = 0.85
BODY_PARTS = ['nose', 'left_ear', 'right_ear']


class Analyzer:
    def __init__(self, video_path):
        self.video_path = Path(video_path)
        self.loader = Loader(video_path=video_path)
        self.dlc_live = DLCLive(EXPORTED_MODEL_PATH, processor=Processor())
        self.is_dlc_live_initiated = False
        self.saved_frames = {}
        self.validate_video()
        self.dlc_config = self.load_dlc_config()

    def run_pose(self, frames=None, is_save_frames=False) -> pd.DataFrame:
        """
        Run Pose Estimation
        :param frames: List of frames IDs needed to be analyzed (ignore the rest)
        :param is_save_frames: True for saving frames in self.saved_frames
        :return: Dataframe with frames as index and body parts as columns
        """
        if frames:
            frames.sort()
        cap = cv2.VideoCapture(self.video_path.as_posix())
        res = []
        frame_id = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if frames and frame_id not in frames:
                continue
            if ret:
                if not self.is_dlc_live_initiated:
                    self.dlc_live.init_inference(frame)
                    self.is_dlc_live_initiated = True
                if is_save_frames:
                    self.saved_frames[frame_id] = frame
                pred = self.dlc_live.get_pose(frame)

                res.append(self.create_pred_df(pred, frame_id))
            frame_id += 1
            if frames and frame_id > frames[-1]:
                break

        return pd.concat(res)

    def create_pred_df(self, pred, frame_id):
        zf = pd.DataFrame(pred, index=self.dlc_config['bodyparts'], columns=['x', 'y', 'prob']).loc[BODY_PARTS, :]
        zf.loc[zf['prob'] < PROBABILITY_THRESH, ['x', 'y']] = np.nan
        s = pd.DataFrame(pd.concat([zf['x'], zf['y']]), columns=[frame_id]).T
        s.columns = pd.MultiIndex.from_product([['x', 'y'], zf.index]).swaplevel(0, 1)
        s.sort_index(axis=1, level=0, inplace=True)
        return s

    def validate_video(self):
        assert self.video_path.exists(), f'video {self.video_path.name} does not exist'
        assert self.video_path.suffix in ['.avi', '.mp4'], f'suffix {self.video_path.suffix} not supported'

    @staticmethod
    def load_dlc_config():
        return yaml.load(open(DLC_CONFIG_FILE), Loader=yaml.FullLoader)
