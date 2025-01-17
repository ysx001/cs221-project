from __future__ import print_function

import os.path as osp
import pickle
from glob import glob
import csv

import cv2
import numpy as np
import scipy.io as sio
import torch
import torchvision.transforms as tvt
from PIL import Image
from torch.utils import data

from code.utils.segmentation.render import render
from code.utils.segmentation.transforms import \
  pad_and_or_crop, random_affine, custom_greyscale_numpy

__all__ = ["DiffSeg"]
RENDER_DATA = True
NUM_SLICES = 90

class _Mri(data.Dataset):
  """Base class
  This contains fields and methods common to all Mri datasets:
  DiffSeg
  """

  def __init__(self, config=None, split=None, purpose=None, preload=False):
    super(_Mri, self).__init__()

    self.split = split
    self.purpose = purpose

    self.root = config.dataset_root

    # always used (labels fields used to make relevancy mask for train)
    self.gt_k = config.gt_k
    self.input_sz = config.input_sz

    # only used if purpose is train
    if purpose == "train":
      self.out_dir = osp.join(osp.join(config.out_root, str(config.model_ind)), "train")
      self.use_random_scale = config.use_random_scale
      if self.use_random_scale:
        self.scale_max = config.scale_max
        self.scale_min = config.scale_min
      self.flip_p = config.flip_p  # 0.5
    elif purpose == "test":
      self.out_dir = osp.join(osp.join(config.out_root, str(config.model_ind)), "test")

    self.files = []
    self.images = []
    self.labels = []

    self.preload = preload
    if self.preload:
      self._preload_data()

    cv2.setNumThreads(0)

  def _prepare_train(self, index, img, label):
    # This returns gpu tensors.
    img_torch, label, mask = self._prepare_test(index, img, label)

    img2_torch = img_torch
    # (img2) do affine if nec, tf_mat changes
    affine2_to_1 = torch.zeros([2, 3]).to(torch.float32).cuda()  # identity
    affine2_to_1[0, 0] = 1
    affine2_to_1[1, 1] = 1

    # (img2) do random flip, tf_mat changes
    if np.random.rand() > self.flip_p:
      img2_torch = torch.flip(img2_torch, dims=[2])  # horizontal, along width

      # applied affine, then flip, new = flip * affine * coord
      # (flip * affine)^-1 is just flip^-1 * affine^-1.
      # No order swap, unlike functions...
      # hence top row is negated
      affine2_to_1[0, :] *= -1.

    return img_torch, img2_torch, affine2_to_1, mask

  def _prepare_test(self, index, img, label):
    # This returns cpu tensors.
    #   Image: 3D with channels last, float32, in range [0, 1] (normally done
    #     by ToTensor).
    #   Label map: 2D, flat int64, [0 ... sef.gt_k - 1]
    # label is passed in canonical [0 ... 181] indexing

    # print (img.shape[:2], label.shape)
    img = img.astype(np.float32)
    label = label.astype(np.int32)

    # center crop to input sz
    img, _ = pad_and_or_crop(img, self.input_sz, mode="centre")
    label, _ = pad_and_or_crop(label, self.input_sz, mode="centre")

    img = img.astype(np.float32) / 1.
    img_torch = torch.from_numpy(img).permute(2, 0, 1)

    # convert to coarse if required, reindex to [0, gt_k -1], and get mask

    mask = torch.ones(self.input_sz, self.input_sz).to(torch.uint8)

    if RENDER_DATA:
      sio.savemat(self.out_dir + ("_data_%d.mat" % index), \
                       mdict={("test_data_img_%d" % index): img,
                       ("test_data_label_post_%d" % index): label})

    # dataloader must return tensors (conversion forced in their code anyway)
    return img_torch, torch.from_numpy(label), mask

  def __getitem__(self, index):
    subject_idx = index // NUM_SLICES
    slice_idx = index % NUM_SLICES
    # print(subject_idx, slice_idx, index)
    subject_id = self.files[subject_idx]
    image, label = self._load_data(subject_id, slice_idx)

    if self.purpose == "train":
      return self._prepare_train(index, image, label)
    else:
      assert (self.purpose == "test")
      return self._prepare_test(index, image, label)

  def __len__(self):
    return len(self.files) * NUM_SLICES

  def _check_gt_k(self):
    raise NotImplementedError()

  def _filter_label(self):
    raise NotImplementedError()

  def _set_files(self):
    raise NotImplementedError()

  def _load_data(self, image_id, slice_idx):
    raise NotImplementedError()


# ------------------------------------------------------------------------------
# Handles which images are eligible

class DiffSeg(_Mri):
  """Base class
  This contains fields and methods common to DiffSeg dataSets
  """

  def __init__(self, **kwargs):
    super(DiffSeg, self).__init__(**kwargs)

    self.label_idx = {}
    with open("code/datasets/segmentation/labelNameCount.csv") as label_counts:
      reader = csv.reader(label_counts)
      for rows in reader:
          label = rows[0]
          idx = rows[1]
          self.label_idx[label] = idx

    self._set_files()

  def _set_files(self):
    if self.split in ["all"]:
      subjects = sorted(glob(osp.join(self.root, 'mwu100307')))
      # print(len(subjects))
      self.files = subjects
    else:
      raise ValueError("Invalid split name: {}".format(self.split))

  def _load_data(self, subject_id, slice_idx):
    image_mat = sio.loadmat(osp.join(self.root, subject_id, "data.mat"))
    
    # shape (90, 108, 90, 4)
    # each slice is 90 * 108
    # 90 slices per subject
    # 4 channels, each channel representing b=0, dwi, md and fa
    image = image_mat["imgs"][:,:,slice_idx,:]
    # using the aparc final FreeSurfer segmentation results
    label = image_mat["segs"][:, :, slice_idx, 1]

    for i in range(len(label)):
      for j in range(len(label[0])):
          label[i, j] = self.label_idx[str(label[i, j])]

    return image, label
