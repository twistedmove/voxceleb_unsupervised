#!/usr/bin/python
#-*- coding: utf-8 -*-

import sys, time, os, argparse, socket
import numpy
import pdb
import torch
import glob
import zipfile
import datetime
from tuneThreshold import tuneThresholdfromScore
from SpeakerNet import SpeakerNet
from DatasetLoader import get_data_loader

parser = argparse.ArgumentParser(description = "SpeakerNet");

## Data loader
parser.add_argument('--max_frames', type=int, default=180,  help='Input length to the network');
parser.add_argument('--eval_frames', type=int, default=350,  help='Input length to the network');
parser.add_argument('--batch_size', type=int, default=200,  help='Batch size');
parser.add_argument('--nDataLoaderThread', type=int, default=20, help='Number of loader threads');

## Training details
parser.add_argument('--test_interval', type=int, default=5, help='Test and save every [test_interval] epochs');
parser.add_argument('--max_epoch',      type=int, default=150, help='Maximum number of epochs');
parser.add_argument('--trainfunc', type=str, default="angleproto",    help='Loss function');
parser.add_argument('--augment_anchor', dest='augment_anchor', action='store_true', help='Augment anchor')
parser.add_argument('--augment_type',   type=int, default=3, help='0: no augment, 1: noise only, 2: noise or RIR, 3: noise and RIR');

## Learning rates
parser.add_argument('--lr', type=float, default=0.001,      help='Learning rate');
parser.add_argument("--lr_decay", type=float, default=0.95, help='Learning rate decay every [test_interval] epochs');

## Load and save
parser.add_argument('--initial_model',  type=str, default="", help='Initial model weights');
parser.add_argument('--save_path',      type=str, default="./data/exp1", help='Path for model and logs');

## Training and test data
parser.add_argument('--train_list', type=str, default="",   help='Train list');
parser.add_argument('--test_list',  type=str, default="",   help='Evaluation list');
parser.add_argument('--train_path', type=str, default="voxceleb2", help='Absolute path to the train set');
parser.add_argument('--test_path',  type=str, default="voxceleb1", help='Absolute path to the test set');
parser.add_argument('--musan_path',  type=str, default="musan_split", help='Absolute path to the test set');

## For test only
parser.add_argument('--eval', dest='eval', action='store_true', help='Eval only')

## Model definition
parser.add_argument('--model', type=str,        default="ResNetSE34L",     help='Name of model definition');
parser.add_argument('--encoder_type', type=str, default="SAP",  help='Type of encoder');
parser.add_argument('--nOut', type=int,         default=512,    help='Embedding size in the last FC layer');

args = parser.parse_args();

## Initialise directories
model_save_path     = args.save_path+"/model"
result_save_path    = args.save_path+"/result"

if not(os.path.exists(model_save_path)):
    os.makedirs(model_save_path)
        
if not(os.path.exists(result_save_path)):
    os.makedirs(result_save_path)

## Load models
s = SpeakerNet(**vars(args));

it          = 1;
prevloss    = float("inf");
sumloss     = 0;

## Load model weights
modelfiles = glob.glob('%s/model0*.model'%model_save_path)
modelfiles.sort()

if len(modelfiles) >= 1:
    s.loadParameters(modelfiles[-1]);
    print("Model %s loaded from previous state!"%modelfiles[-1]);
    it = int(os.path.splitext(os.path.basename(modelfiles[-1]))[0][5:]) + 1
elif(args.initial_model != ""):
    s.loadParameters(args.initial_model);
    print("Model %s loaded!"%args.initial_model);

for ii in range(0,it-1):
    if ii % args.test_interval == 0:
        clr = s.updateLearningRate(args.lr_decay) 

## Evaluation code
if args.eval == True:
        
    sc, lab, trials = s.evaluateFromList(args.test_list, print_interval=100, test_path=args.test_path, eval_frames=args.eval_frames)
    result = tuneThresholdfromScore(sc, lab, [1, 0.1]);
    print('EER %2.4f'%result[1])

    ## Save scores
    print('Type desired file name to save scores. Otherwise, leave blank.')
    userinp = input()

    while True:
        if userinp == '':
            quit();
        elif os.path.exists(userinp):
            print('%s already exists. Try again.'%(userinp))
            userinp = input()
        else:
            with open(userinp,'w') as outfile:
                for vi, val in enumerate(sc):
                    outfile.write('%.4f %s\n'%(val,trials[vi]))
            quit();

## save code
pyfiles = glob.glob('./*.py')
strtime = datetime.datetime.now().strftime("%Y%m%d%H%M%S")

zipf = zipfile.ZipFile(result_save_path+ '/run%s.zip'%strtime, 'w', zipfile.ZIP_DEFLATED)
for file in pyfiles:
    zipf.write(file)
zipf.close()

f = open(result_save_path + '/run%s.cmd'%strtime, 'w')
f.write(' '.join(sys.argv))
f.close()

## Write args to scorefile
scorefile = open(result_save_path+"/scores.txt", "a+");

## Initialise data loader
trainLoader = get_data_loader(args.train_list, **vars(args));

clr = s.updateLearningRate(1)

while(1):   
    print(time.strftime("%Y-%m-%d %H:%M:%S"), it, "Training %s with LR %f..."%(args.model,max(clr)));

    ## Train network
    loss, traineer = s.train_network(loader=trainLoader);

    ## Validate and save
    if it % args.test_interval == 0:

        print(time.strftime("%Y-%m-%d %H:%M:%S"), it, "Evaluating...");

        sc, lab, _ = s.evaluateFromList(args.test_list, print_interval=100, test_path=args.test_path, eval_frames=args.eval_frames)
        result = tuneThresholdfromScore(sc, lab, [1, 0.1]);

        print(args.save_path);
        print(time.strftime("%Y-%m-%d %H:%M:%S"), "LR %f, TEER/TAcc %2.2f, TLOSS %f, VEER %2.4f"%( max(clr), traineer, loss, result[1]));
        scorefile.write("IT %d, LR %f, TEER/TAcc %2.2f, TLOSS %f, VEER %2.4f\n"%(it, max(clr), traineer, loss, result[1]));

        scorefile.flush()

        clr = s.updateLearningRate(args.lr_decay) 

        s.saveParameters(model_save_path+"/model%09d.model"%it);
        
        with open(model_save_path+"/model%09d.eer"%it, 'w') as eerfile:
            eerfile.write('%.4f'%result[1])

    else:

        print(time.strftime("%Y-%m-%d %H:%M:%S"), "LR %f, TEER/TAcc %2.2f, TLOSS %f"%( max(clr), traineer, loss));
        scorefile.write("IT %d, LR %f, TEER/TAcc %2.2f, TLOSS %f\n"%(it, max(clr), traineer, loss));

        scorefile.flush()

    if it >= args.max_epoch:
        quit();

    it+=1;
    print("");

scorefile.close();





