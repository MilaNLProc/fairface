from __future__ import print_function, division
import warnings
from appdirs import *
from dnl_mapper import *
warnings.filterwarnings("ignore")
import os.path

import pandas as pd
import torch
import torch.nn as nn
import numpy as np
import torchvision
from torchvision import datasets, models, transforms
import dlib
import os
import argparse
import shutil

def rect_to_bb(rect):
    # take a bounding predicted by dlib and convert it
    # to the format (x, y, w, h) as we would normally do
    # with OpenCV
    x = rect.left()
    y = rect.top()
    w = rect.right() - x
    h = rect.bottom() - y
    # return a tuple of (x, y, w, h)
    return (x, y, w, h)

class FairFacePredictor:

    def __init__(self):

        download_all_models()

    def detect_face(self, image_paths, default_max_size=800, size=300, padding=0.25):

        SAVE_DETECTED_AT = get_cache_directory()
        models_path = get_cache_directory("models")

        if not os.path.exists(SAVE_DETECTED_AT):
            os.makedirs(SAVE_DETECTED_AT)

        cnn_face_detector = dlib.cnn_face_detection_model_v1(os.path.join(models_path, MMOD))
        sp = dlib.shape_predictor(os.path.join(models_path, SHAPE))
        base = 2000  # largest width and height
        for index, image_path in enumerate(image_paths):
            if index % 1000 == 0:
                print('---%d/%d---' % (index, len(image_paths)))
            img = dlib.load_rgb_image(image_path)

            old_height, old_width, _ = img.shape

            if old_width > old_height:
                new_width, new_height = default_max_size, int(default_max_size * old_height / old_width)
            else:
                new_width, new_height = int(default_max_size * old_width / old_height), default_max_size
            img = dlib.resize_image(img, rows=new_height, cols=new_width)

            dets = cnn_face_detector(img, 1)
            num_faces = len(dets)
            if num_faces == 0:
                print("Sorry, there were no faces found in '{}'".format(image_path))
                continue
            # Find the 5 face landmarks we need to do the alignment.
            faces = dlib.full_object_detections()
            for detection in dets:
                rect = detection.rect
                faces.append(sp(img, rect))
            images = dlib.get_face_chips(img, faces, size=size, padding=padding)

            # TODO: THIS IS WHERE WE DIVERGE FROM THE ORIGINAL CODE

            for idx, image in enumerate(images):
                img_name = image_path.split("/")[-1]
                path_sp = img_name.split(".")
                face_name = os.path.join(SAVE_DETECTED_AT, path_sp[0] + "_" + "face" + str(idx) + "." + path_sp[-1])
                dlib.save_image(image, face_name)
                break

    def predidct_age_gender_race(self):

        SAVE_DETECTED_AT = get_cache_directory()

        models_path = get_cache_directory("models")

        img_names = [os.path.join(SAVE_DETECTED_AT, x) for x in os.listdir(SAVE_DETECTED_AT)]

        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

        model_fair_7 = torchvision.models.resnet34(pretrained=True)
        model_fair_7.fc = nn.Linear(model_fair_7.fc.in_features, 18)
        model_fair_7.load_state_dict(torch.load(os.path.join(models_path,MODEL_7)))
        model_fair_7 = model_fair_7.to(device)
        model_fair_7.eval()

        model_fair_4 = torchvision.models.resnet34(pretrained=True)
        model_fair_4.fc = nn.Linear(model_fair_4.fc.in_features, 18)
        model_fair_4.load_state_dict(torch.load(os.path.join(models_path, MODEL_4)))
        model_fair_4 = model_fair_4.to(device)
        model_fair_4.eval()

        trans = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])
        # img pth of face images
        face_names = []
        # list within a list. Each sublist contains scores for all races. Take max for predicted race
        race_scores_fair = []
        gender_scores_fair = []
        age_scores_fair = []
        race_preds_fair = []
        gender_preds_fair = []
        age_preds_fair = []
        race_scores_fair_4 = []
        race_preds_fair_4 = []

        for index, img_name in enumerate(img_names):
            if index % 1000 == 0:
                print("Predicting... {}/{}".format(index, len(img_names)))

            face_names.append(img_name)
            image = dlib.load_rgb_image(img_name)
            image = trans(image)
            image = image.view(1, 3, 224, 224)  # reshape image to match model dimensions (1 batch size)
            image = image.to(device)

            # fair
            outputs = model_fair_7(image)
            outputs = outputs.cpu().detach().numpy()
            outputs = np.squeeze(outputs)

            race_outputs = outputs[:7]
            gender_outputs = outputs[7:9]
            age_outputs = outputs[9:18]

            race_score = np.exp(race_outputs) / np.sum(np.exp(race_outputs))
            gender_score = np.exp(gender_outputs) / np.sum(np.exp(gender_outputs))
            age_score = np.exp(age_outputs) / np.sum(np.exp(age_outputs))

            race_pred = np.argmax(race_score)
            gender_pred = np.argmax(gender_score)
            age_pred = np.argmax(age_score)

            race_scores_fair.append(race_score)
            gender_scores_fair.append(gender_score)
            age_scores_fair.append(age_score)

            race_preds_fair.append(race_pred)
            gender_preds_fair.append(gender_pred)
            age_preds_fair.append(age_pred)

            # fair 4 class
            outputs = model_fair_4(image)
            outputs = outputs.cpu().detach().numpy()
            outputs = np.squeeze(outputs)

            race_outputs = outputs[:4]
            race_score = np.exp(race_outputs) / np.sum(np.exp(race_outputs))
            race_pred = np.argmax(race_score)

            race_scores_fair_4.append(race_score)
            race_preds_fair_4.append(race_pred)

        result = pd.DataFrame([face_names,
                               race_preds_fair,
                               race_preds_fair_4,
                               gender_preds_fair,
                               age_preds_fair,
                               race_scores_fair, race_scores_fair_4,
                               gender_scores_fair,
                               age_scores_fair, ]).T

        result.columns = ['face_name_align',
                          'race_preds_fair',
                          'race_preds_fair_4',
                          'gender_preds_fair',
                          'age_preds_fair',
                          'race_scores_fair',
                          'race_scores_fair_4',
                          'gender_scores_fair',
                          'age_scores_fair']
        result.loc[result['race_preds_fair'] == 0, 'race'] = 'White'
        result.loc[result['race_preds_fair'] == 1, 'race'] = 'Black'
        result.loc[result['race_preds_fair'] == 2, 'race'] = 'Latino_Hispanic'
        result.loc[result['race_preds_fair'] == 3, 'race'] = 'East Asian'
        result.loc[result['race_preds_fair'] == 4, 'race'] = 'Southeast Asian'
        result.loc[result['race_preds_fair'] == 5, 'race'] = 'Indian'
        result.loc[result['race_preds_fair'] == 6, 'race'] = 'Middle Eastern'

        # race fair 4

        result.loc[result['race_preds_fair_4'] == 0, 'race4'] = 'White'
        result.loc[result['race_preds_fair_4'] == 1, 'race4'] = 'Black'
        result.loc[result['race_preds_fair_4'] == 2, 'race4'] = 'Asian'
        result.loc[result['race_preds_fair_4'] == 3, 'race4'] = 'Indian'

        # gender
        result.loc[result['gender_preds_fair'] == 0, 'gender'] = 'Male'
        result.loc[result['gender_preds_fair'] == 1, 'gender'] = 'Female'

        # age
        result.loc[result['age_preds_fair'] == 0, 'age'] = '0-2'
        result.loc[result['age_preds_fair'] == 1, 'age'] = '3-9'
        result.loc[result['age_preds_fair'] == 2, 'age'] = '10-19'
        result.loc[result['age_preds_fair'] == 3, 'age'] = '20-29'
        result.loc[result['age_preds_fair'] == 4, 'age'] = '30-39'
        result.loc[result['age_preds_fair'] == 5, 'age'] = '40-49'
        result.loc[result['age_preds_fair'] == 6, 'age'] = '50-59'
        result.loc[result['age_preds_fair'] == 7, 'age'] = '60-69'
        result.loc[result['age_preds_fair'] == 8, 'age'] = '70+'

        result = result[['face_name_align',
                         'race', 'race4',
                         'gender', 'age',
                         'race_scores_fair', 'race_scores_fair_4',
                         'gender_scores_fair', 'age_scores_fair']]

        if len(os.listdir(SAVE_DETECTED_AT)) != 0:
            shutil.rmtree(SAVE_DETECTED_AT)

        return result


if __name__ == "__main__":

    dlib.DLIB_USE_CUDA = True

    images = ["bibi.jpeg", "bobi.jpeg"]

    fair = FairFacePredictor()
    fair.detect_face(images)

    data = (fair.predidct_age_gender_race())
    data.to_csv("saved.csv")

