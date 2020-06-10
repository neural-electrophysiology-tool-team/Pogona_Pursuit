import torch
import Detector.Yolo4.darknet as darknet4
from Detector.models import Darknet
from utils.utils import load_classes, non_max_suppression
import cv2 as cv
from ctypes import c_int, pointer
import numpy as np

"""
- All detectors implement the function detect_image(), that return a (number of detections) X 5 Numpy array.
The (row - single detection) array format is left_x-left_y-width-height-confidence.
"""

class Detector:
    def detect_image(self, img, orig_width, orig_height, conf_thres=0.8, nms_thres=0.5):
        """
        Return detection array for the supplied image.
        img - The image as a pytorch tensor. Expecting img_size x img_size dimensions.
        conf_thres - confidence threshold for detection
        nms_thres - threshold for non-max suppression
        """
        pass


class Detector_v3(Detector):
    def __init__(self,
                 model_def="Detector/Yolo3/config/yolov3-custom.cfg",
                 weights_path="Detector/Yolo3/weights/yolov3-pogonahead.pth",
                 class_path="Detector/Yolo3/classes.names",
                 img_size=416):
        
        self.model_def = model_def
        self.weights_path = weights_path
        self.class_path = class_path
        self.img_size = img_size

        if torch.cuda.is_available():
            device = torch.device("cuda")
        else:
            device = torch.device("cpu")
            print("WARNING: GPU is not available")

        # Initiate model
        self.model = Darknet(self.model_def, img_size=self.img_size)
        self.model.load_state_dict(torch.load(weights_path, map_location=device))
        if torch.cuda.is_available():
            self.model.cuda()
        self.model.eval()
        self.classes = load_classes(class_path)
     
    def set_input_size(width, height):
        self.input_width = width
        self.input_height = height
        
        # update transforms: scale and pad image
        ratio = min(img_size/width, img_size/height)
        imw = round(width * ratio)
        imh = round(height * ratio)
        # resize + pad can be done with open cv and numpy!!
        self.resize_transform = transforms.Compose([transforms.Resize((imh, imw)),
                                                    transforms.Pad((max(int((imh-imw)/2),0), 
                                                                    max(int((imw-imh)/2),0), max(int((imh-imw)/2),0),
                                                                    max(int((imw-imh)/2),0)), (128,128,128)),
                                                    transforms.ToTensor()])
    
    def xyxy_to_xywh(self,xyxy, output_shape):
        """
        xyxy - an array of xyxy detections in input_size x input_size coordinates.
        output_shape - shape of output array (height, width)
        """
 
        input_size = self.img_size
        
        pad_x = max(output_shape[0] - output_shape[1], 0) * (input_size / max(output_shape))
        pad_y = max(output_shape[1] - output_shape[0], 0) * (input_size / max(output_shape))
        unpad_h = input_size - pad_y
        unpad_w = input_size - pad_x

        x1 = xyxy[:, 0]
        y1 = xyxy[:, 1]
        x2 = xyxy[:, 2]
        y2 = xyxy[:, 3]

        box_h = ((y2 - y1) / unpad_h) * output_shape[0]
        box_w = ((x2 - x1) / unpad_w) * output_shape[1]
        y1 = ((y1 - pad_y // 2) / unpad_h) * output_shape[0]
        x1 = ((x1 - pad_x // 2) / unpad_w) * output_shape[1]
        
        
        # return detections as (num_detections)X5 tensor, with
        # format xywh-conf
        return torch.stack([x1, y1, box_w, box_h,xyxy[:,4]], dim=1)
    
    def detect_image(self, img, orig_width, orig_height, conf_thres=0.8, nms_thres=0.5):
        """
        Return yolo detection array for the supplied image.
        img - The image as numpy array.
        conf_thres - confidence threshold for detection
        nms_thres - threshold for non-max suppression
        """

        img_rgb = cv.cvtColor(img, cv.COLOR_BGR2RGB)
        PIL_img = Image.fromarray(img_rgb)
        self.set_input_size(orig_width, orig_height)
        image_tensor = self.resize_transform(PIL_img).unsqueeze(0)

        if torch.cuda.is_available():
            input_img = image_tensor.type(torch.Tensor).cuda()
        else:
            input_img = image_tensor.type(torch.Tensor)
            
        # run inference on the model and get detections
        with torch.no_grad():
            detections = self.model(input_img)
            detections = non_max_suppression(detections,
                                             conf_thres, nms_thres)
        detections = detections[0]
        
        if detections is not None:
            return self.xyxy_to_xywh(detections,(orig_height,orig_width)).numpy()
        
        return None
    

class Detector_v4:
    def __init__(self,
                 cfg_path="Detector/Yolo4/yolo-obj.cfg",
                 weights_path="Detector/Yolo4/yolo-obj_best.weights",
                 meta_path="Detector/Yolo4/obj.data"):
        self.net = darknet4.load_net_custom(cfg_path.encode("ascii"),
                                            weights_path.encode("ascii"),
                                            0, 1)
        self.meta = darknet4.load_meta(meta_path.encode("ascii"))
        self.model_width = darknet4.lib.network_width(self.net)
        self.model_height = darknet4.lib.network_height(self.net)
        print("YOlO-V4 Model loaded")
  
    def detect_image(self, img, orig_width, orig_height, conf_thres=0.8, nms_thres=0.5):
        """
        Receive an image as numpy array. Resize image to model size using open-cv.
        Run the image through the network and collect detections.
        Return a numpy array of detections. Each row is x, y, w, h (top-left corner).
        """
        image = cv.cvtColor(img, cv.COLOR_BGR2RGB)
        image = cv.resize(image, (self.model_width, self.model_height), interpolation=cv.INTER_LINEAR)
        image, arr = darknet4.array_to_image(image)
        
        num = c_int(0)
        pnum = pointer(num)
        darknet4.predict_image(self.net, image)
              
        dets = darknet4.get_network_boxes(self.net, orig_width, orig_height, conf_thres, conf_thres, None, 0, pnum, 0)
               
        num = pnum[0]
        if nms_thres:
            darknet4.do_nms_sort(dets, num, self.meta.classes, nms_thres)
        
        
        res = np.zeros((num, 5))
        for i in range(num):
            b = dets[i].bbox
            res[i] = [b.x-b.w/2, b.y-b.h/2, b.w, b.h, dets[i].prob[0]]
        nonzero = res[:, 4] > 0
        res = res[nonzero]
            
        darknet4.free_detections(dets, num)
        #darknet4.free_image(image) # no allocation of memory
        
        
        if res.shape[0] == 0:
            return None
        else:
            return res

