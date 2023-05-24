from const import CONFIG_PATH
import configparser
import json
import pickle
from data_prep.image_loader import ImageLoader
from modelling.local_model_store import LocalModelStore
from experiment_setup.lfw_test_setup import get_lfw_test
from experiment_setup.dataset_filters_setup import setup_dataset_filter
from experiment_setup.dataloaders_setup import dataloaders_setup
from experiment_setup.trainer_setup import get_trainer
from experiment_setup.pairs_behaviour_setup import setup_pairs_reps_behaviour
from data_prep.dlib_aligner_image_loader import DlibAlignerImageLoader
import os

if __name__ == '__main__':
    config = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())
    config.read(CONFIG_PATH)

    im_size = int(config['DATASET']['image_size'])
    post_crop_im_size = int(config['DATASET']['post_crop_im_size'])
    dataset_means = json.loads(config['DATASET']['dataset_means'])
    dataset_stds = json.loads(config['DATASET']['dataset_stds'])
    image_loader = ImageLoader(im_size, post_crop_im_size, dataset_means, dataset_stds)

    filter = setup_dataset_filter(config)

    processed_dataset, num_classes = filter.process_dataset(
        config['DATASET']['raw_dataset_path'],
        config['DATASET']['dataset_name'])

    dataloaders = dataloaders_setup(config, processed_dataset, image_loader)

    model_store = LocalModelStore(config['MODELLING']['architecture'],
                                  config['GENERAL']['root_dir'],
                                  config['GENERAL']['experiment_name'])

    start_epoch = int(config['MODELLING']['start_epoch'])
    end_epoch = int(config['MODELLING']['end_epoch'])

    lfw_tester = get_lfw_test(config, image_loader)

    trainer = get_trainer(config, num_classes, start_epoch, lfw_tester)

    # trainer.train_model(start_epoch, end_epoch, dataloaders)

    # print(lfw_tester.test_performance(trainer.model))

    reps_behaviour_extractor = setup_pairs_reps_behaviour(config, image_loader)

    output = reps_behaviour_extractor.test_behaviour(trainer.model)

    results_path = os.path.join(config['REP_BEHAVIOUR']['reps_results_path'], 'comparisons_face_angles.pkl')
    print('Saving results in ', results_path)
    os.makedirs(config['REP_BEHAVIOUR']['reps_results_path'], exist_ok=True)
    with open(results_path, 'wb') as f:
        pickle.dump(output, f)

    print('done')

    # TODO: Add option to start from existing models.
    # TODO: Divide the analysis from training and from the data prep - use dir tree as indicator to the model training

