import os
import cv2
import math
import yaml
import numpy as np
from PIL import Image
from pathlib import Path
import argparse

from collections import OrderedDict

from model.edvr_models import EDVRSTFTempRank
from dataset.xray_dataset import XrayVideoTestDatasetSTF

import torch
from torchvision.utils import make_grid
from dataset.dist_util import get_dist_info
from skimage.metrics import structural_similarity as ssim


def tensor2img(tensor, rgb2bgr=True, out_type=np.uint8, min_max=(0, 1)):
    """Convert torch Tensors into image numpy arrays.

    After clamping to [min, max], values will be normalized to [0, 1].

    Args:
        tensor (Tensor or list[Tensor]): Accept shapes:
            1) 4D mini-batch Tensor of shape (B x 3/1 x H x W);
            2) 3D Tensor of shape (3/1 x H x W);
            3) 2D Tensor of shape (H x W).
            Tensor channel should be in RGB order.
        rgb2bgr (bool): Whether to change rgb to bgr.
        out_type (numpy type): output types. If ``np.uint8``, transform outputs
            to uint8 type with range [0, 255]; otherwise, float type with
            range [0, 1]. Default: ``np.uint8``.
        min_max (tuple[int]): min and max values for clamp.

    Returns:
        (Tensor or list): 3D ndarray of shape (H x W x C) OR 2D ndarray of
        shape (H x W). The channel order is BGR.
    """
    if not (torch.is_tensor(tensor) or (isinstance(tensor, list) and all(torch.is_tensor(t) for t in tensor))):
        raise TypeError(f'tensor or list of tensors expected, got {type(tensor)}')

    if torch.is_tensor(tensor):
        tensor = [tensor]
    result = []
    for _tensor in tensor:
        _tensor = _tensor.squeeze(0).float().detach().cpu().clamp_(*min_max)
        _tensor = (_tensor - min_max[0]) / (min_max[1] - min_max[0])

        n_dim = _tensor.dim()
        if n_dim == 4:
            img_np = make_grid(_tensor, nrow=int(math.sqrt(_tensor.size(0))), normalize=False).numpy()
            img_np = img_np.transpose(1, 2, 0)
            if rgb2bgr:
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        elif n_dim == 3:
            img_np = _tensor.numpy()
            img_np = img_np.transpose(1, 2, 0)
            if img_np.shape[2] == 1:  # gray image
                img_np = np.squeeze(img_np, axis=2)
            else:
                if rgb2bgr:
                    img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        elif n_dim == 2:
            img_np = _tensor.numpy()
        else:
            raise TypeError(f'Only support 4D, 3D or 2D tensor. But received with dimension: {n_dim}')
        if out_type == np.uint8:
            # Unlike MATLAB, numpy.unit8() WILL NOT round by default.
            img_np = (img_np * 255.0).round()
        img_np = img_np.astype(out_type)
        result.append(img_np)
    if len(result) == 1:
        result = result[0]
    return result

def ordered_yaml():
    """Support OrderedDict for yaml.

    Returns:
        tuple: yaml Loader and Dumper.
    """
    try:
        from yaml import CDumper as Dumper
        from yaml import CLoader as Loader
    except ImportError:
        from yaml import Dumper, Loader

    _mapping_tag = yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG

    def dict_representer(dumper, data):
        return dumper.represent_dict(data.items())

    def dict_constructor(loader, node):
        return OrderedDict(loader.construct_pairs(node))

    Dumper.add_representer(OrderedDict, dict_representer)
    Loader.add_constructor(_mapping_tag, dict_constructor)
    return Loader, Dumper

def yaml_load(f):
    """Load yaml file or string.

    Args:
        f (str): File path or a python string.

    Returns:
        dict: Loaded dict.
    """
    if os.path.isfile(f):
        with open(f, 'r') as f:
            return yaml.load(f, Loader=ordered_yaml()[0])
    else:
        return yaml.load(f, Loader=ordered_yaml()[0])
    

if __name__ == '__main__':
    
    if 'XFusion' in Path(os.getcwd()).parts:
        if Path(os.getcwd()).name == 'inference':
            cdir = Path(os.getcwd())
        elif Path(os.getcwd()).name == 'XFusion':
            cdir = Path(os.getcwd()) + '/inference'
    elif Path(os.getcwd()).name == 'conda':
        cdir = str(Path(os.getcwd())) + '/XFusion/inference'
    else:
        raise Exception('can not parse current working directory')
    os.chdir(cdir)
    print(f"current directory is: {cdir}")
    parser = argparse.ArgumentParser()
    parser.add_argument('--lo_frame_sep', default=1)
    parser.add_argument('--hi_frame_sep', default=1)
    parser.add_argument('--b0', default=False)
    parser.add_argument('--img_class', default='dataset1')
    args = parser.parse_args()
    mode = 'stf'
    
    b0 = int(args.b0)
    print(f'inference under {mode} mode')
    topk_times = 5
    lo_frame_sep = int(args.lo_frame_sep)
    hi_frame_sep = int(args.hi_frame_sep)
    img_class = str(args.img_class)
    print(f'LR frame separation is {lo_frame_sep}')
    print(f'HR frame separation is {hi_frame_sep}')

    
    opt_path = rf'configs/config_{img_class}.yml'
    print(f"path to config file is: {opt_path}")
    opt = yaml_load(opt_path)

    test_set_name = opt['name']
    gt_size = opt['datasets']['val']['gt_size']
    out_dir = Path(f'../inf_data/{test_set_name}_stf_lr_r_{lo_frame_sep}_hr_d_{hi_frame_sep*2}_b0_{b0}')
    out_dir.mkdir(exist_ok=True,parents=True)
    
    # default input file structure is: */dataset[n]/HR and */dataset[n]/LR
    # the postfixes are appended to the parent directory
    opt['datasets']['val']['dataroot_lq'] = [dr+f'_b0_{b0}' if Path(dr).name.lower() != 'lr' else str(Path(dr).parents[0])+f'_b0_{b0}'+f"/{Path(dr).name}" for dr in opt['datasets']['val']['dataroot_lq']]
    opt['datasets']['val']['dataroot_gt'] = [dr+f'_b0_{0}' if Path(dr).name.lower() != 'hr' else str(Path(dr).parents[0])+f'_b0_{b0}'+f"/{Path(dr).name}" for dr in opt['datasets']['val']['dataroot_gt']]
    print(f"data paths are: {opt['datasets']['val']['dataroot_lq']} for LR and {opt['datasets']['val']['dataroot_gt']} for HR")
    
    opt['dist'] = False
    opt['manual_seed'] = 10
    torch.manual_seed(opt['manual_seed'])
    model_config = opt['network_g']
    model_config['num_frame'] = topk_times
    model_config['num_frame_hi'] = 0
    model_config['center_frame_idx'] = 1
    model = EDVRSTFTempRank(**model_config)
    
    model.load_state_dict(torch.load(opt['path']['pretrain_network_g'])['params'])
    try:
        model.cuda()
    except:
        print("no gpu detected")
    dataset_opt = opt['datasets']['val']
    dataset_opt['scale'] = 4
    dataset_opt['gt_size'] = gt_size[:2]
    test_set = XrayVideoTestDatasetSTF(dataset_opt)
    test_loader = torch.utils.data.DataLoader(dataset=test_set, batch_size=1, shuffle=False, num_workers=0)
    
    dataset = test_loader.dataset
    rank, world_size = get_dist_info()
    psnrs, aads, atts, ssims, masks = [], [], [], [], []
    
    for idx in range(rank+1, len(dataset), world_size):
        results = []

        val_data_ = dataset[idx]
        val_data_['lq'].unsqueeze_(0)
        if 'gt' in list(val_data_.keys()):
            val_data_['gt'].unsqueeze_(0)
        else:
            val_data_['image'].unsqueeze_(0)
        
        if 'gt' in list(val_data_.keys()):
            val_data = {'lq':val_data_['lq'].cuda(), 'gt':val_data_['gt'].cuda(), 'hq':val_data_['hq'][None,:,:,:].cuda()}
        else:
            val_data = {'lq':val_data_['lq'].cuda(), 'image':val_data_['image'].cuda(), 'hq':val_data_['hq'][None,:,:,:].cuda()}
            
        val_data['lq'] = torch.cat((dataset[max(0,int(idx-lo_frame_sep))]['lq'][model_config['center_frame_idx'],:,:,:].unsqueeze(0),\
                    val_data['lq'][0,model_config['center_frame_idx'],:,:,:].unsqueeze(0).cpu(),\
                    dataset[min(len(dataset)-1,int(idx+lo_frame_sep))]['lq'][model_config['center_frame_idx'],:,:,:].unsqueeze(0)),dim=0).unsqueeze(0).cuda()
        
        if 'gt' in list(dataset[max(0,int(idx//(hi_frame_sep*2)*hi_frame_sep*2))].keys()):
            gt_key = 'gt'
        else:
            gt_key = 'image'
        if len(dataset[max(0,int(idx//(hi_frame_sep*2)*hi_frame_sep*2))][gt_key].size()) == 4:
            val_data['hq'] = torch.cat((dataset[max(0,int(idx//(hi_frame_sep*2)*hi_frame_sep*2))][gt_key][0,:,:,:].unsqueeze(0), dataset[min(gt_size[2],int((idx//(hi_frame_sep*2)+1)*hi_frame_sep*2))][gt_key][0,:,:,:].unsqueeze(0))).unsqueeze(0).cuda()
        elif len(dataset[max(0,int(idx//(hi_frame_sep*2)*hi_frame_sep*2))][gt_key].size()) == 3:
            val_data['hq'] = torch.cat((dataset[max(0,int(idx//(hi_frame_sep*2)*hi_frame_sep*2))][gt_key].unsqueeze(0), dataset[min(gt_size[2],int((idx//(hi_frame_sep*2)+1)*hi_frame_sep*2))][gt_key].unsqueeze(0))).unsqueeze(0).cuda()
        
        if (idx == max(0,int(idx//(hi_frame_sep*2)*hi_frame_sep*2))) or (idx == min(len(dataset)-1,int(idx+lo_frame_sep))):
            masks.append(1)
        else:
            masks.append(0)
        
        with torch.no_grad():
            results = model(val_data)
            result, corr = results['out'], results['corr_score']
            
            result_img = (tensor2img(result).astype(float))
        result_img[result_img>255] = 255
        
        if 'gt' in list(val_data.keys()):
            gt = val_data['gt'].detach().cpu()
        else:
            gt = val_data['image'].detach().cpu()
        hi_img = tensor2img(gt).astype(float)
        if len(hi_img.shape) == 3:
            hi_img = hi_img[:,:,0]
        elif len(hi_img.shape) == 2:
            pass

        diff = (result_img - hi_img)
        mse = np.mean((diff)**2)
        psnr = 10. * np.log10(255. * 255. / mse)
        aad = abs(diff).mean()
        _ssim = ssim(result_img,hi_img, data_range=255)
        print(f"psnr is {psnr} dB")
        print(f"aad is {aad}")
        print(f"ssim is {_ssim}")
        psnrs.append(psnr)
        aads.append(aad)
        ssims.append(_ssim)
        print(f"attention high is {corr.detach().cpu().squeeze().numpy()[-1]}")
        atts.append(corr.detach().cpu().squeeze().numpy())
        Image.fromarray(result_img.astype(np.uint8)).save(f"{(out_dir / Path(val_data_['lq_path']).stem)}_{psnr}.png")

        att_all = np.vstack(atts)
        if att_all.shape[1] == 4:
            result_dict = {'psnr':psnrs, 'aad': aads, 'ssim': ssims, 't-1 lo':att_all[:,0], 't lo': att_all[:,1], 't+1 lo': att_all[:,2], 't hi': att_all[:,3]}
        elif att_all.shape[1] == 5:
            result_dict = {'psnr':psnrs, 'aad': aads, 'ssim': ssims, 't-1 lo':att_all[:,0], 't lo': att_all[:,1], 't+1 lo': att_all[:,2], 't-1 hi': att_all[:,3], 't+1 hi': att_all[:,4]}
        
    
    if masks:
        result_dict['mask'] = masks
    import pandas as pd
    pd.DataFrame(result_dict).to_csv(out_dir / f'error_{test_set_name}_stf_lr_r_{lo_frame_sep}_hr_d_{2*hi_frame_sep}_b0_{b0}.csv')
    print('done')