from const import CONFIG_PATH
import mlflow
import const
import glob
import argparse
import time
import datetime
import os
import configparser
import json
from data_prep.image_loader import ImageLoader
from modelling.local_model_store import LocalModelStore
from experiment_setup.lfw_test_setup import get_lfw_test
from experiment_setup.dataset_filters_setup import setup_dataset_filter
from experiment_setup.dataloaders_setup import dataloaders_setup
from experiment_setup.generic_trainer_setup import get_trainer
from experiment_setup.pairs_behaviour_setup import setup_pairs_reps_behaviour
import modelling.finetuning
import pandas as pd
from representation.analysis.rep_dist_mat import DistMatrixComparer

mlflow.set_tracking_uri(const.MLFLOW_TRACKING_URI)


def get_args():
    parser = argparse.ArgumentParser()

    parser.add_argument("--config_path", type=str, default=CONFIG_PATH)
    parser.add_argument("--config_dir", type=str, default=None)
    parser.add_argument("--debug", type=bool, default=const.DEBUG)

    args = parser.parse_args()
    return args


def run_experiment(config_path):
    # Get the configuration file
    print(datetime.datetime.now())
    start = time.perf_counter()
    config = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())
    config.read(config_path)
    print("Running experiment " + config['GENERAL']['experiment_name'])
    if mlflow.get_experiment_by_name(config['GENERAL']['experiment_name']) is None:
        mlflow.create_experiment(config['GENERAL']['experiment_name'], artifact_location=os.path.join(const.MLFLOW_ARTIFACT_STORE, config['GENERAL']['experiment_name']))
    mlflow.set_experiment(config['GENERAL']['experiment_name'])


    with mlflow.start_run():
        print(mlflow.get_artifact_uri())
        mlflow.log_artifact(config_path)
        # Create image loader (by the configuration)
        im_size = json.loads(config['DATASET']['image_size'])
        mlflow.log_param('image_size', im_size)
        post_crop_im_size = int(config['DATASET']['post_crop_im_size'])
        mlflow.log_param('post_crop_im_size', post_crop_im_size)
        dataset_means = json.loads(config['DATASET']['dataset_means'])
        mlflow.log_param('dataset_means', dataset_means)
        dataset_stds = json.loads(config['DATASET']['dataset_stds'])
        mlflow.log_param('dataset_stds', dataset_stds)
        crop_scale = None
        if 'crop_scale' in config['DATASET']:
            crop_scale = json.loads(config['DATASET']['crop_scale'])
            crop_scale = (crop_scale['max'], crop_scale['min'])
        image_loader = ImageLoader(im_size, post_crop_im_size, dataset_means, dataset_stds, crop_scale=crop_scale)

        # Create the dataset filters by config (if they are needed)
        filter = setup_dataset_filter(config)

        # Activate the filters
        processed_dataset, num_classes = filter.process_dataset(
            config['DATASET']['raw_dataset_path'],
            config['DATASET']['dataset_name'])

        print("training on dataset: ", processed_dataset)
        mlflow.log_param('training_dataset', processed_dataset)
        # Create dataloader for the training
        dataloaders = dataloaders_setup(config, processed_dataset, image_loader)

        # Get access to pre trained models
        model_store = LocalModelStore(config['MODELLING']['architecture'],
                                      config['GENERAL']['root_dir'],
                                      config['GENERAL']['experiment_name'])
        mlflow.log_param('architecture', config['MODELLING']['architecture'])
        mlflow.log_param('experiment_name', config['GENERAL']['experiment_name'])
        mlflow.log_param('root_dir', config['GENERAL']['root_dir'])

        start_epoch = int(config['MODELLING']['start_epoch'])
        end_epoch = int(config['MODELLING']['end_epoch'])
        mlflow.log_param('start_epoch', start_epoch)
        mlflow.log_param('end_epoch', end_epoch)

        # creating the lfw tester
        lfw_tester = get_lfw_test(config, image_loader)

        num_classes = int(config['MODELLING']['num_classes'])
        mlflow.log_param('num_classes', num_classes)

        # Creating the trainer and loading the pretrained model if specified in the configuration
        trainer = get_trainer(config, num_classes, start_epoch, lfw_tester)

        if 'FINETUNING' in config:
            mlflow.log_param('finetuning', True)
            model = modelling.finetuning.append_classes(trainer.model, int(config['FINETUNING']['num_classes']))
            mlflow.log_param('finetuning_classes', int(config['FINETUNING']['num_classes']))
            model = modelling.finetuning.freeze_layers(model, int(config['FINETUNING']['freeze_end']))
            mlflow.log_param('freeze_depth', int(config['FINETUNING']['freeze_end']))
            trainer.model = model

        # Will train the model from start_epoch to (end_epoch - 1) with the given dataloaders
        trainer.train_model(start_epoch, end_epoch, dataloaders)

        if lfw_tester is not None:
            lfw_results = lfw_tester.test_performance(trainer.model)
            print(lfw_results)
            lfw_path = os.path.join(config['LFW_TEST']['reps_results_path'], config['LFW_TEST']['output_filename'])
            os.makedirs(config['LFW_TEST']['reps_results_path'], exist_ok=True)
            lfw_results.to_csv(lfw_path)

        reps_behaviour_extractor = setup_pairs_reps_behaviour(config, image_loader)

        if reps_behaviour_extractor is not None:
            output = reps_behaviour_extractor.compare_lists(trainer.model)

            if output is not None:
                if type(output) == pd.DataFrame:
                    results_path = os.path.join(config['REP_BEHAVIOUR']['reps_results_path'],
                                                config['REP_BEHAVIOUR']['output_filename'] + '.csv')

                    print('Saving results in ', results_path)

                    output.to_csv(results_path)
                    mlflow.log_artifact(results_path)

        end = time.perf_counter()
        print(datetime.datetime.now())
        print((end - start) / 3600)
        print((time.process_time()) / 3600)
        print('done')

    # TODO: Divide the analysis from training and from the data prep - use dir tree as indicator to the model training


if __name__ == '__main__':
    args = get_args()
    const.DEBUG = args.debug
    if args.config_dir is not None:
        config_paths = glob.glob(os.path.join(args.config_dir, '*.cfg'))
        for path in config_paths:
            run_experiment(path)
    else:
        run_experiment(args.config_path)
