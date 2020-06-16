import numpy as np
import cv2 as cv
import time
import matplotlib.pyplot as plt
import torch
from tqdm import tqdm
from PIL import Image
from torchvision import transforms
import matplotlib.pyplot as plt



def calc_centroid(pred_tensor):
    x1 = pred_tensor[:, 0]
    y1 = pred_tensor[:, 1]
    box_w = pred_tensor[:, 2]
    box_h = pred_tensor[:, 3]

    return np.stack([x1+(box_w//2), y1+(box_h//2)], axis=1)


def hsv_to_rgb(H,S,V):
    """
    transform angle to BGR color as 3-tuple
    """
    C = S*V
    X = C*(1-np.abs((H/60)%2-1))
    m=V-C 
    
    if H >= 0 and H < 60:
        r,g,b = C,X,0
    elif H >= 60 and H < 120:
        r,g,b = X,C,0
    elif H >= 120 and H < 180:
        r,g,b = 0,C,X
    elif H >= 180 and H < 240:
        r,g,b = 0,X,C
    elif H >= 240 and H <300:
        r,g,b = X,0,C
    else:
        r,g,b = C,0,X
    
    roun = lambda x: int(round(x))
    
    # return b,g,r
    return roun((b+m)*255),roun((g+m)*255),roun((r+m)*255)


def torch_resize_transform(width, height, detector):
    img_size = detector.img_size
    # scale and pad image
    ratio = min(img_size/width, img_size/height)
    imw = round(width * ratio)
    imh = round(height * ratio)
    return transforms.Compose([transforms.Resize((imh, imw)),
                               transforms.Pad((max(int((imh-imw)/2), 0),
                                               max(int((imw-imh)/2), 0), max(int((imh-imw)/2), 0),
                                               max(int((imw-imh)/2), 0)), (128, 128, 128)),
                               transforms.ToTensor()])


def vec_to_bgr(vec):
    """
    input: 2D vector
    return: 3-tuple, specifying BGR color using HSV formula as
    """
    
    # transform to [-pi,pi] and then to degrees
    angle = np.arctan2(vec[1], vec[0])*180/np.pi
    
    # transform to [0,360]
    angle = (angle + 360) % 360
    return hsv_to_rgb(angle, 1, 1)


def time_to_bgr(k,arrowWindow): # DOES NOT WORK - TODO 
    # map the relative position of the frame to [0,360] angle and then to hue
    rel = (arrowWindow-k)/arrowWindow
    return hsv_to_rgb(0,1,rel)
    

def draw_arrow(frame,
               frameCounter,
               centroids,
               arrowWindow,
               k,
               vis_angle=True,
               windowSize=1,
               scale=2.5):
    """
    draws the direction of the velocity vector from (arrowWindow) frames back
    directions based on the first discrete derivative of the 2D coordinates of
    windowSize consecutive centroids of the detecions, if both exist
    """
    
    # initial arrow
    if frameCounter<windowSize:
        return
    
    # if no prediction at t - windowSize, bo drawing
    if np.isnan(centroids[frameCounter-windowSize, 0]) or np.isnan(centroids[frameCounter, 0]):
        return

    arrowBase = tuple(centroids[frameCounter-windowSize].astype(int))
    arrowHead = tuple(centroids[frameCounter].astype(int))
    
    # scale head for better visibility
    extend_x = scale*(arrowHead[0]-arrowBase[0])
    extend_y = scale*(arrowHead[1]-arrowBase[1])
    
    new_x = arrowHead[0] + extend_x
    new_y = arrowHead[1] + extend_y
    
    if new_x<0:
        new_x=0
    if new_x > frame.shape[1]:
        new_x = frame.shape[1]
        
    if new_y<0:
        new_y = 0
    if new_y>frame.shape[0]:
        new_y=frame.shape[0]
    
    arrowHead = (new_x,new_y)
    
    # compute color based on angle or time
    if vis_angle:
        vec_color = vec_to_bgr([arrowHead[0]-arrowBase[0],arrowHead[1]-arrowBase[1]])
    else:
        vec_color = time_to_bgr(k,arrowWindow)
    
    cv.arrowedLine(frame,arrowBase,arrowHead,color=vec_color, thickness=2,tipLength=0.2,line_type=cv.LINE_AA)


def draw_bounding_boxes(frame, detections, detector, color=(0, 0, 255)):

    font = cv.FONT_HERSHEY_COMPLEX
    scale = 0.4
    thickness = cv.FILLED
    margin = 4

    if detections is not None:
        unique_labels = np.unique(detections[:, -1])

        # browse detections and draw bounding boxes
        for x1, y1, box_w, box_h, conf in detections:
            x1 = int(x1)
            y1 = int(y1)
            box_w = int(box_w)
            box_h = int(box_h)

            text = str(round(conf, 2))
            txt_size = cv.getTextSize(text, font, scale, thickness)
            end_x = int(x1 + txt_size[0][0] + margin)
            end_y = int(y1 + txt_size[0][1] + margin)

            cv.rectangle(frame, (x1, y1), (end_x, end_y), color, thickness)
            cv.rectangle(frame, (x1, y1), (x1+box_w, y1+box_h), color, 2)
            cv.putText(frame, text, (x1, end_y - margin), font, scale,
                       (255, 255, 255), 1, cv.LINE_AA)


def update_centroids(detections, centroids, frameCounter):
    """
    update the detection centroids array
    """
    if detections.shape[0] > 1 and frameCounter > 1:
        prev = centroids[frameCounter - 1][:2]
        detected_centroids = calc_centroid(detections)
        deltas = prev - detected_centroids
        dists = np.linalg.norm(deltas, axis=1)
        arg_best = np.argmin(dists)
        centroid = detected_centroids[arg_best]
        detection = detections[arg_best:arg_best+1]
    else:
        centroid = calc_centroid(detections)[0]
        detection = detections

    centroids[frameCounter][0] = centroid[0]
    centroids[frameCounter][1] = centroid[1]
    centroids[frameCounter][2] = detection[0][4]

    return detection


def draw_k_arrows(frame,frameCounter,centroids,arrowWindow,visAngle,windowSize,scale=5):
    for k in range(arrowWindow):
        draw_arrow(frame,frameCounter-k,centroids,arrowWindow,k,visAngle,windowSize,scale)


def draw_k_centroids(frame,frameCounter,centroids,k):
    if k > frameCounter:
        k = frameCounter-1
    
    for j in range(k):
        if np.isnan(centroids[frameCounter-j][0]):
            continue
        x = int(centroids[frameCounter-j][0])
        y = int(centroids[frameCounter-j][1])
        cv.circle(frame,
                  center = (x,y),
                  radius=2,
                  color= (0,0,255),
                  thickness=-1,
                  lineType=cv.LINE_AA)


def save_pred_video(video_path,
                    output_path,
                    detector,
                    start_frame=0,
                    num_frames=None,
                    frame_rate=None,
                    windowSize=1,
                    arrowWindow=20,
                    visAngle=True,
                    dots=False):
    print("saving to: ", output_path)
    vcap = cv.VideoCapture(video_path)

    if start_frame != 0:
        vcap.set(cv.CAP_PROP_POS_FRAMES, start_frame)

    if num_frames is None:
        num_frames = int(vcap.get(cv.CAP_PROP_FRAME_COUNT)) - start_frame

    width = int(vcap.get(3))
    height = int(vcap.get(4))
    detector.set_input_size(width, height)

    print(f'width: {width}, height: {height}')
    if frame_rate is None:
        frame_rate = vcap.get(cv.CAP_PROP_FPS)

    videowriter = cv.VideoWriter(output_path, cv.VideoWriter_fourcc(*'mp4v'),
                                 frame_rate, (width, height))

    frameCounter = 0
    cmap = plt.get_cmap('tab20b')
    colors = [cmap(i)[:3] for i in np.linspace(0, 1, 20)]
    

    # while vcap.isOpened(): # while the stream is open
    #inference_time = np.zeros(num_frames)
    centroids = np.empty((num_frames,3))
    centroids[:] = np.nan

    ###############################
    times = dict()
    for key in ['Read','Rsz_inf','Write']:
        times[key] = np.zeros(num_frames)    
    ################################
    
    for frameCounter in tqdm(range(num_frames)):
        start_time = time.time() ##
        ret, frame = vcap.read()
        times['Read'][frameCounter] = time.time() - start_time ##

        if not ret:
            print("error reading frame")
            break
                
        start_time = time.time() ##
        detections = detector.detect_image(frame)
        times['Rsz_inf'][frameCounter] = time.time() - start_time ##
               
        if detections is not None:
            detection = update_centroids(detections,centroids,frameCounter)
            draw_bounding_boxes(frame, detections, detector)
        
        if not dots:
            draw_k_arrows(frame,frameCounter,centroids,arrowWindow,visAngle,windowSize,scale=5)
        else:
            draw_k_centroids(frame,frameCounter,centroids,arrowWindow)

        start_time = time.time()##
        videowriter.write(frame)
        times['Write'][frameCounter] = time.time() - start_time ##
    
    #######################################
    for key in times.keys():
        print(key,': ',times[key].mean())
    ########################################
    vcap.release()
    videowriter.release()

    return times, centroids


def dots_overlay(overlay, centroids):
    fade = 0.99
    overlay[:, :, 3] = (overlay[:, :, 3] * fade).astype(np.uint8)

    if np.isnan(centroids[-1, 0]):
        return

    x = int(centroids[-1, 0])
    y = int(centroids[-1, 1])

    cv.circle(overlay,
              center=(x, y), radius=2, color=(0,0,255,255),
              thickness=-1,
              lineType=cv.LINE_AA)


def arrows_overlay(overlay, centroids):
    fade = 0.99
    overlay[:, :, 3] = (overlay[:, :, 3] * fade).astype(np.uint8)
    if (centroids.shape[0] < 2):
        return

    if np.isnan(centroids[-1, 0]) or np.isnan(centroids[-2, 0]):
        return

    end_x = int(centroids[-1, 0])
    end_y = int(centroids[-1, 1])
    start_x = int(centroids[-2, 0])
    start_y = int(centroids[-2, 1])

    vec_color = vec_to_bgr([end_x-start_x, end_y-start_y])
    cv.arrowedLine(overlay,
                   (start_x, start_y),
                   (end_x, end_y),
                   color=(vec_color[0], vec_color[1], vec_color[2], 255),
                   thickness=1,
                   tipLength=0.2,
                   line_type=cv.LINE_AA)


def overlay_video(input_path, output_path, detector, overlay_fn, draw_bbox=True,
                  start_frame=0, num_frames=None, frame_rate=None):

    vcap = cv.VideoCapture(input_path)

    if start_frame != 0:
        vcap.set(cv.CAP_PROP_POS_FRAMES, start_frame)

    if num_frames is None:
        num_frames = int(vcap.get(cv.CAP_PROP_FRAME_COUNT)) - start_frame

    if frame_rate is None:
        frame_rate = vcap.get(cv.CAP_PROP_FPS)

    width = int(vcap.get(3))
    height = int(vcap.get(4))
    detector.set_input_size(width, height)

    videowriter = cv.VideoWriter(output_path, cv.VideoWriter_fourcc(*'mp4v'),
                                 frame_rate, (width, height))

    centroids = np.empty((num_frames, 2))
    centroids[:] = np.nan
    
    overlay = np.zeros((height, width, 4), np.uint8)

    for frame_num in tqdm(range(num_frames)):
        ret, frame = vcap.read()

        if not ret:
            print("error reading frame")
            break
                
        detections = detector.detect_image(frame)
               
        if detections is not None:
            detection = update_centroids(detections, centroids, frame_num)
            if draw_bbox:
                draw_bounding_boxes(frame, detections, detector)

        overlay_fn(overlay, centroids[:frame_num+1, :])
        alpha_s = overlay[:, :, 3] / 255.0
        alpha_l = 1.0 - alpha_s
        for c in range(3):
            frame[:, :, c] = (alpha_s * overlay[:, :, c] +
                              alpha_l * frame[:, :, c])

        videowriter.write(frame)
    
    vcap.release()
    videowriter.release()

    
def plot_no_video(centroids, num_frames,vid_name,
                  width=1440,
                  height=1080,
                  draw_window=240,
                  frame_rate=60):
    
    videowriter = cv.VideoWriter(vid_name, cv.VideoWriter_fourcc(*'mp4v'),
                                 frame_rate, (width, height))
    
    frame = 255 * np.ones((height,width,3)).astype('uint8')
    for frameCounter in tqdm(range(num_frames)):
        frame.fill(255)
        draw_k_centroids(frame,frameCounter,centroids,draw_window)
        
        videowriter.write(frame)
    
    videowriter.release()
    
    
def plot_with_figure(input_name,
                     output_name,
                     centroids,
                     num_frames,
                     width=1440,
                     height=1080,
                     draw_window=240,
                     frame_rate=60):
    
    FIG_WID_EXT = 960
    
    vcap = cv.VideoCapture(input_name)
    
    if num_frames is None:
        num_frames = int(vcap.get(cv.CAP_PROP_FRAME_COUNT))

    width = int(vcap.get(3))
    height = int(vcap.get(4))

    print(f'width: {width}, height: {height}')
    if frame_rate is None:
        frame_rate = vcap.get(cv.CAP_PROP_FPS)

    videowriter = cv.VideoWriter(output_name, cv.VideoWriter_fourcc(*'mp4v'),
                                 frame_rate, (width+FIG_WID_EXT, height))

    velocities_mag = compute_velocity(centroids)
    confies = centroids[:,2]
    
    write_frame = 255 * np.ones((height,width+FIG_WID_EXT,3)).astype('uint8')
    for frameCounter in tqdm(range(num_frames)):
        ret, frame = vcap.read()

        if not ret:
            print("error reading frame")
            break
        
        draw_k_centroids(frame,frameCounter,centroids,draw_window)
        
        draw_figure_on_frame(write_frame,frame,frameCounter,velocities_mag,confies,num_frames)
        
        videowriter.write(write_frame)
    
    videowriter.release()

def draw_figure_on_frame(write_frame,
                         vid_frame,
                         frameCounter,
                         velocities,
                         confidences,
                         total_frames):
    """
    draw updating data beside video
    """
    WIDTH_INCH = 10
    HEIGHT_INCH = 5
    DPI = 96
    MARKER_SIZE = 50
    
    
    PLOT_BACK = 300
    
    fig = plt.figure(figsize=(WIDTH_INCH,HEIGHT_INCH),dpi=DPI)
    
    start_range = max(frameCounter-PLOT_BACK,0)
    end_range = frameCounter
    
    plt.scatter(np.arange(start_range,end_range),
                confidences[start_range:end_range],s=MARKER_SIZE,c='r')
    plt.scatter(np.arange(start_range,end_range),
                velocities[start_range:end_range],s=MARKER_SIZE,c='b')
    plt.xlim(start_range-10,end_range+10)
    plt.ylim(0,1)
    plt.rcParams.update({'font.size':14})
    fig.canvas.draw()
    width, height = fig.get_size_inches() * fig.get_dpi()
    width, height = int(width), int(height)
    
    fig_image = np.frombuffer(fig.canvas.tostring_rgb(), dtype='uint8').reshape(height, width, 3)
    plt.clf()
    plt.close()
    """
    print(f'fig_image shape: {fig_image.shape}')
    print(f'vid_frame shape: {vid_frame.shape}')
    print(f'frame shape: {write_frame.shape}')
    """
    
    write_frame[:,:vid_frame.shape[1],:] = vid_frame
    write_frame[240:240+480,vid_frame.shape[1]:,:] = fig_image
    
    
    

def compute_velocity(centroids):
    """
    computes normalized magnitude of velocity (divided by max value of array)
    """
    veloc = np.diff(centroids,axis=0)
    veloc = np.apply_along_axis(np.linalg.norm,1,veloc)
    norm_speed = np.percentile(veloc[~np.isnan(veloc)],99) # reject top 5% outliers
    veloc[veloc>norm_speed] = np.nan
    veloc = veloc /norm_speed 
    
    return veloc