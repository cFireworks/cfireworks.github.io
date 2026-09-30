---
title: Object Detection API学习
date: 2019-05-07 12:00:00
updated: 2020-09-26 12:00:00
categories:
  - Framework
tags:
  - deep learning
  - tensorflow
  - object detection
---

TensorFlow开源的`Object Detection API`是一个基于TensorFlow的开源框架，可以方便地构建、训练和部署目标检测模型，和其他目标检测库，例如mmdetection相比，Object Detection API的优势是方便部署。

项目地址：[https://github.com/tensorflow/models/tree/master/research/object_detection](https://github.com/tensorflow/models/tree/master/research/object_detection)

项目简介：该API目前能够同时支持Tensorflow 2和Tensorflow 1

TF 1.x文档：[https://github.com/tensorflow/models/blob/master/research/object_detection/g3doc/tf1.md](https://github.com/tensorflow/models/blob/master/research/object_detection/g3doc/tf1.md)

TF 2.x文档：[https://github.com/tensorflow/models/blob/master/research/object_detection/g3doc/tf2.md](https://github.com/tensorflow/models/blob/master/research/object_detection/g3doc/tf2.md)

## 一、安装环境

首先从github克隆项目仓库，该API是tensorflow的models仓库中的一个项目

```shell
git clone https://github.com/tensorflow/models.git
```

### 1.1 Docker安装方式

```shell
# 进入仓库根目录
cd models
# 创建并运行docker容器
docker build -f research/object_detection/dockerfiles/tf1/Dockerfile -t od .
docker run -it od
```

### 1.2 python包安装方式

#### 新版本2.x分支

在最新版本中，首先将protos中的`.proto`文件转换为`.py`文件，其次直接通过`setup.py`进行api的安装，该脚本主要负责安装一下依赖：`pillow`,`lxml`,`matplotlib`,`Cython`,`contextlib2`,`tf-slim`,`six`,`pycocotools`,`scipy`,`pandas`,并将slim下的相关package进行打包。

```shell
pip install tensorflow
cd models/research
# 编译protos
protoc object_detection/protos/*.proto --python_out=.
# Install TensorFlow Object Detection API.
cp object_detection/packages/tf1/setup.py .
python -m pip install --use-feature=2020-resolver .
```

#### 旧版本1.x分支

在旧版本中，通常要手动安装python依赖包，且1.x版本的tensorflow的cpu和gpu版本是分开的，因此需要特别注意。

```shell
# cpu版本tensorflow安装
pip install tensorflow
# gpu版本tensorflow安装
pip install tensorflow-gpu
# 其他依赖包安装
sudo apt-get install protobuf-compiler python-pil python-lxml python-tk
pip install  Cython
pip install  contextlib2
pip install  jupyter
pip install  matplotlib
pip install  Cython
pip install  pillow
pip install  lxml
```

添加系统环境变量

```shell
# From tensorflow/models/research/
export PYTHONPATH=$PYTHONPATH:`pwd`:`pwd`/slim
# 长期添加环境路径,在~/.bashrc末尾添加
vim ~/.bashrc
```

### 1.3 测试是否安装成功

```shell
# 进入research目录下
python object_detection/builders/model_builder_test.py
```

## 二、使用自定义数据集训练模型

训练模型需要准备四样东西，分别是tfrecord格式的数据、labelmap标签映射、预训练模型以及模型对应的配置文件。

### 2.1 基于Pascal VOC标注的图像数据集准备

```python
import tensorflow as tf
from lxml import etree
import io
import os
from object_detection.utils import dataset_util
from object_detection.utils import label_map_util

def dict_to_tf_example(data,  dataset_directory, label_map_dict):
    full_path = os.path.join(dataset_directory, data['filename'])
    with tf.gfile.GFile(full_path, 'rb') as fid:
        encoded_jpg = fid.read()

    image_format = b'png'
    width = int(data['size']['width'])
    height = int(data['size']['height'])

    xmin = []
    ymin = []
    xmax = []
    ymax = []
    classes = []
    classes_text = []

    if 'object' in data:
        for obj in data['object']:
            if obj['name'] == 'dolly':
                continue
            xmin.append(float(obj['bndbox']['xmin']) / width)
            ymin.append(float(obj['bndbox']['ymin']) / height)
            xmax.append(float(obj['bndbox']['xmax']) / width)
            ymax.append(float(obj['bndbox']['ymax']) / height)
            classes_text.append(obj['name'].encode('utf8'))
            classes.append(label_map_dict[obj['name']])

    example = tf.train.Example(features=tf.train.Features(feature={
        'image/height': dataset_util.int64_feature(height),
        'image/width': dataset_util.int64_feature(width),
        'image/filename': dataset_util.bytes_feature(
            data['filename'].encode('utf8')),
        'image/source_id': dataset_util.bytes_feature(
            data['filename'].encode('utf8')),
        'image/encoded': dataset_util.bytes_feature(encoded_jpg),
        'image/format': dataset_util.bytes_feature(image_format),
        'image/object/bbox/xmin': dataset_util.float_list_feature(xmin),
        'image/object/bbox/xmax': dataset_util.float_list_feature(xmax),
        'image/object/bbox/ymin': dataset_util.float_list_feature(ymin),
        'image/object/bbox/ymax': dataset_util.float_list_feature(ymax),
        'image/object/class/text': dataset_util.bytes_list_feature(classes_text),
        'image/object/class/label': dataset_util.int64_list_feature(classes),
    }))
    return example

def create_tf_record_pascal(pascal_files, dataset_directory, label_map_file, output_path):
    label_map_dict = label_map_util.get_label_map_dict(label_map_file)
    writer = tf.python_io.TFRecordWriter(output_path)
    for pascal_file in pascal_files:
        with tf.gfile.GFile(pascal_file, 'r') as fid:
            xml_str = fid.read()
        xml = etree.fromstring(xml_str)
        data = dataset_util.recursive_parse_xml_to_dict(xml)['annotation']
        tf_example = dict_to_tf_example(data, dataset_directory, label_map_dict)
        writer.write(tf_example.SerializeToString())
    writer.close()

def convert_from_pascal_files(data_dir):
    """
        # 创建数据集
        # ---data
        # ------images
        # ---------xx.png
        # ------labels
        # ---------xx.xml
        # ------output
        # ---------label_map.pbtxt
        # ---------train.record
        # ---------val.record
    """
    anno_dir = os.path.join(data_dir, "labels")
    pascal_files = os.listdir(anno_dir)
    train_pascal_files = [os.path.join(
        anno_dir, name) for name in pascal_files if int(name.split('.')[0]) % 5 != 0]
    eval_pascal_files = [os.path.join(
        anno_dir, name) for name in pascal_files if int(name.split('.')[0]) % 5 == 0]
    img_dir = os.path.join(data_dir, "images")
    label_map_file = os.path.join(data_dir, "output/labelmap.pbtxt")
    # 训练集
    train_record_path = os.path.join(data_dir, "output/train.record")
    create_tf_record_pascal(train_pascal_files, img_dir,
                            label_map_file, train_record_path)
    # 验证集
    eval_record_path = os.path.join(data_dir, "output/eval.record")
    create_tf_record_pascal(eval_pascal_files, img_dir,
                            label_map_file, eval_record_path)
```

### 2.2 labelmap.pbtxt准备

可以用自带的labelmap.pbtxt格式来表示标注映射，也可以自己用字典来表示。

```shell
item {
  id: 1
  name: 'nine'
}

item {
  id: 2
  name: 'ten'
}

item {
  id: 3
  name: 'jack'
}

item {
  id: 4
  name: 'queen'
}

item {
  id: 5
  name: 'king'
}

item {
  id: 6
  name: 'ace'
}
```

### 2.3 预训练模型

预训练模型通常是基于不同分类网络，例如ResNet、VGG，与不同目标检测模型结合的预训练模型。

TF 1.x版本模型集：[https://github.com/tensorflow/models/blob/master/research/object_detection/g3doc/tf1_detection_zoo.md](https://github.com/tensorflow/models/blob/master/research/object_detection/g3doc/tf1_detection_zoo.md)

TF 2.x版本模型集：[https://github.com/tensorflow/models/blob/master/research/object_detection/g3doc/tf2_detection_zoo.md](https://github.com/tensorflow/models/blob/master/research/object_detection/g3doc/tf2_detection_zoo.md)

### 2.4 模型配置文件

通常预训练模型包含着pipeline.config文件是预训练的参数配置，可以基于此进行修改，以faster_rcnn_resnet50_coco模型为例，它的配置参数主要有`model`,`train_config`,`train_input_reader`,`eval_config`,`eval_input_reader`这几部分。

#### 2.4.1 model配置模块

```shell
model {
  faster_rcnn {
    // 目标类别数
    num_classes: 99
    // 输入图像调整
    image_resizer {
      keep_aspect_ratio_resizer {
        min_dimension: 600
        max_dimension: 800
      }
    }
    // 注册了的特征提取网络
    feature_extractor {
      type: "faster_rcnn_resnet50"
      first_stage_features_stride: 16
    }
    // 一阶段anchor生成参数
    first_stage_anchor_generator {
      grid_anchor_generator {
        height_stride: 16
        width_stride: 16
        scales: 0.5
        scales: 1
        scales: 2
        aspect_ratios: 0.5
        aspect_ratios: 1.0
        aspect_ratios: 2.0
      }
    }
    // 一阶段box预测的超参数，L2正则化，初始化值
    first_stage_box_predictor_conv_hyperparams {
      op: CONV
      regularizer {
        l2_regularizer {
          weight: 0.0
        }
      }
      initializer {
        truncated_normal_initializer {
          stddev: 0.01
        }
      }
    }
    // 一阶段非极大值抑制阈值以及候选区数量
    first_stage_nms_score_threshold: 0.3
    first_stage_nms_iou_threshold: 0.7
    first_stage_max_proposals: 600
    first_stage_localization_loss_weight: 2.0
    first_stage_objectness_loss_weight: 1.0
    initial_crop_size: 14
    maxpool_kernel_size: 2
    maxpool_stride: 2
    // 二阶段box预测
    second_stage_box_predictor {
      mask_rcnn_box_predictor {
        fc_hyperparams {
          op: FC
          regularizer {
            l2_regularizer {
              weight: 0.0
            }
          }
          initializer {
            variance_scaling_initializer {
              factor: 1.0
              uniform: true
              mode: FAN_AVG
            }
          }
        }
        use_dropout: false
        dropout_keep_probability: 1.0
      }
    }
    // 二阶段后处理，非极大值抑制
    second_stage_post_processing {
      batch_non_max_suppression {
        score_threshold: 0.0
        iou_threshold: 0.6
        max_detections_per_class:50 
        max_total_detections: 200
      }
      score_converter: SOFTMAX
    }
    second_stage_localization_loss_weight: 2.0
    second_stage_classification_loss_weight: 1.0
  }
}
```

#### 2.4.2 train_config配置模块

```shell
train_config {
  // batch数量
  batch_size: 1
  // 数据增强选项
  data_augmentation_options {
    random_horizontal_flip {
    }
    random_crop_pad_image{
    }
    random_rgb_to_gray{
    }
    random_adjust_brightness {
    }
    random_adjust_contrast{
    }
  }
  // 优化器参数设置
  optimizer {
    momentum_optimizer {
      learning_rate {
        manual_step_learning_rate {
          initial_learning_rate: 0.001
          schedule {
            step: 5000
            learning_rate: 0.0003
          }
          schedule {
            step: 15000
            learning_rate: 0.00003
          }
        }
      }
      momentum_optimizer_value: 0.9
    }
    use_moving_average: false
  }
  gradient_clipping_by_norm: 10.0
  // 预训练模型路径
  fine_tune_checkpoint: "/xxx/xxx/faster_rcnn_resnet50_coco/model.ckpt"
  from_detection_checkpoint: true
  num_steps: 20000
}
```

训练配置中有比较丰富的数据增强选项可供使用，详细可以见`preprocessor.proto`文件：

```python
message PreprocessingStep {
  oneof preprocessing_step {
    NormalizeImage normalize_image = 1;
    RandomHorizontalFlip random_horizontal_flip = 2;
    RandomPixelValueScale random_pixel_value_scale = 3;
    RandomImageScale random_image_scale = 4;
    RandomRGBtoGray random_rgb_to_gray = 5;
    RandomAdjustBrightness random_adjust_brightness = 6;
    RandomAdjustContrast random_adjust_contrast = 7;
    RandomAdjustHue random_adjust_hue = 8;
    RandomAdjustSaturation random_adjust_saturation = 9;
    RandomDistortColor random_distort_color = 10;
    RandomJitterBoxes random_jitter_boxes = 11;
    RandomCropImage random_crop_image = 12;
    RandomPadImage random_pad_image = 13;
    RandomCropPadImage random_crop_pad_image = 14;
    RandomCropToAspectRatio random_crop_to_aspect_ratio = 15;
    RandomBlackPatches random_black_patches = 16;
    RandomResizeMethod random_resize_method = 17;
    ScaleBoxesToPixelCoordinates scale_boxes_to_pixel_coordinates = 18;
    ResizeImage resize_image = 19;
    SubtractChannelMean subtract_channel_mean = 20;
    SSDRandomCrop ssd_random_crop = 21;
    SSDRandomCropPad ssd_random_crop_pad = 22;
    SSDRandomCropFixedAspectRatio ssd_random_crop_fixed_aspect_ratio = 23;
    SSDRandomCropPadFixedAspectRatio ssd_random_crop_pad_fixed_aspect_ratio = 24;
    RandomVerticalFlip random_vertical_flip = 25;
    RandomRotation90 random_rotation90 = 26;
    RGBtoGray rgb_to_gray = 27;
    ConvertClassLogitsToSoftmax convert_class_logits_to_softmax = 28;
    RandomAbsolutePadImage random_absolute_pad_image = 29;
    RandomSelfConcatImage random_self_concat_image = 30;
    AutoAugmentImage autoaugment_image = 31;
    DropLabelProbabilistically drop_label_probabilistically = 32;
    RemapLabels remap_labels = 33;
    RandomJpegQuality random_jpeg_quality = 34;
    RandomDownscaleToTargetPixels random_downscale_to_target_pixels = 35;
    RandomPatchGaussian random_patch_gaussian = 36;
    RandomSquareCropByScale random_square_crop_by_scale = 37;
    RandomScaleCropAndPadToSquare random_scale_crop_and_pad_to_square = 38;
  }
}
```

#### 2.4.3 其余配置模块

其余主要是训练集输入和评估集输入，只要设置好路径以及label_map_path即可

### 2.5 运行命令

运行主要包括训练的运行、评估的运行以及模型的导出，如下所示：

#### 2.5.1 模型训练

```shell
# 进入research目录下
cd ~/tensorflow/models/research
# 设置配置文件路径变量
PIPELINE_CONFIG_PATH=/xxx/xxx/pretrained_models/faster_rcnn_resnet50_coco/faster_rcnn_resnet50_coco.config
# 设置模型输出目录变量
MODEL_DIR=/xxx/xxx/output_model
# 设置评估样本的采样数
SAMPLE_1_OF_N_EVAL_EXAMPLES=1
# 运行训练命令
python object_detection/legacy/train.py \
        --logtostderr \
        --train_dir=${MODEL_DIR} \
        --pipeline_config_path=${PIPELINE_CONFIG_PATH}
```

#### 2.5.2 模型评估

```shell
# 进入research目录下
cd ~/tensorflow/models/research
# 设置配置文件路径变量
PIPELINE_CONFIG_PATH=/xxx/xxx/pretrained_models/faster_rcnn_resnet50_coco/faster_rcnn_resnet50_coco.config
# 设置模型输出目录变量
MODEL_DIR=/xxx/xxx/output_model
# 设置评估结果输出目录变量
EVAL_DIR=/xxx/xxx/output_model/eval
# 运行评估命令
python object_detection/legacy/eval.py \
        --logtostderr \
        --pipeline_config_path=${PIPELINE_CONFIG_PATH} \
        --checkpoint_dir=${MODEL_DIR} \
        --eval_dir=${EVAL_DIR}
```

#### 2.5.3 模型导出

```shell
# 进入research目录下
cd ~/tensorflow/models/research
# 设置输入类型
INPUT_TYPE=image_tensor
# 设置配置文件路径
PIPELINE_CONFIG_PATH=/xxx/xxx/pretrained_models/faster_rcnn_resnet50_coco/faster_rcnn_resnet50_coco.config
# 设置模型目录变量,frozen_pb格式结果输出目录
TRAINED_CKPT_PREFIX=/xxx/xxx/output_model/model.ckpt-xxxx
EXPORT_DIR=/xxx/xxx/frozen_output
# 运行模型导出命令，将模型导出为frozen_pb格式
python object_detection/export_inference_graph.py \
    --input_type=${INPUT_TYPE} \
    --pipeline_config_path=${PIPELINE_CONFIG_PATH} \
    --trained_checkpoint_prefix=${TRAINED_CKPT_PREFIX} \
    --output_directory=${EXPORT_DIR}
```