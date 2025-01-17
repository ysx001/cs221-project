import os.path as osp
import numpy as np
import scipy.io as sio
from glob import glob
from sklearn.decomposition import PCA

import torch
import torchvision.models as models
import torchvision.transforms as transforms

from PIL import Image


# MODEL_IDX = 0

ALL_MODELS = [models.densenet161(pretrained=True),
              models.densenet201(pretrained=True),
            #   models.resnext50_32x4d(pretrained=True),
            #   models.resnext101_32x8d(pretrained=True),
              models.resnet101(pretrained=True),
              models.resnet152(pretrained=True),
            #   models.wide_resnet50_2(pretrained=True),
            #   models.wide_resnet101_2(pretrained=True),
              models.vgg19_bn(pretrained=True),
              models.vgg16_bn(pretrained=True)]

ALL_MODEL_FEATURES = [5, 5, 5, 5, 14, 14]


preprocess = transforms.Compose([
    transforms.Resize(224),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225])
])


def make_model(model_idx):
    model = ALL_MODELS[model_idx]
    if model_idx < 2 or model_idx >= 4:
        model = model.features
    else:
        model = torch.nn.Sequential(
            model.conv1, model.bn1, model.relu, model.maxpool,
            model.layer1, model.layer2, model.layer3, model.layer4,
            model.avgpool)
    model = model[:ALL_MODEL_FEATURES[model_idx]]
    model.cuda()
    return model


def extract_feature(model,imgpath):
    model.eval()

    img = Image.open(imgpath)
    img = preprocess(img)
    img.unsqueeze_(0)
    img=img.cuda()
    result = model(img)
    result_npy=result.data.cpu().numpy()

    return result_npy[0]

if __name__=="__main__":
    root='/bmrNAS/people/yuxinh/DL_diffseg/DiffSeg-Data/'
    subjects = sorted(glob(osp.join(root, 'mwu*')))

    # root='/bmrNAS/people/yuxinh/DL_diffseg/MSSeg-Data/'
    # subjects = sorted(glob(osp.join(root, '*')))

    # root='/Users/jason/Documents/HCP'
    # subjects = sorted(glob(osp.join(root, 'mwu*')))

    # print(subjects)
    for model_idx in range(len(ALL_MODELS)):
        model = make_model(model_idx)
        for subject_id in subjects:
            print(subject_id)
            slices = sorted(glob(osp.join(root, subject_id, 'jpg', "im*")))
            ch, h, w = extract_feature(model, slices[0]).shape
            sub_features = np.zeros((ch, h, w, len(slices)))
            for i in range(len(slices)):
                tmp = extract_feature(model, slices[i])
                sub_features[:, :, :, i] = tmp
            sio.savemat(osp.join(root, subject_id, ("features_%s.mat" % (model_idx,))), {
                'features': sub_features,
            })
