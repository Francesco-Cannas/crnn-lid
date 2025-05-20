import os
import shutil
import numpy as np
import argparse
import time
from datetime import datetime
from yaml import safe_load
from collections import namedtuple

import models
import data_loaders
from evaluate import evaluate

from keras.callbacks import ModelCheckpoint, TensorBoard, CSVLogger, EarlyStopping
from keras.optimizers import Adam, RMSprop, SGD
from keras.metrics import Precision, Recall

import tensorflow as tf
import tensorflow.keras.backend as K

def f1_score(y_true, y_pred):
    y_true = K.cast(y_true, 'float32')
    y_pred = K.cast(y_pred, 'float32')
    y_pred = K.round(y_pred)
    
    tp = K.sum(y_true * y_pred, axis=0)
    fp = K.sum((1 - y_true) * y_pred, axis=0)
    fn = K.sum(y_true * (1 - y_pred), axis=0)

    precision = tp / (tp + fp + K.epsilon())
    recall = tp / (tp + fn + K.epsilon())
    f1 = 2 * precision * recall / (precision + recall + K.epsilon())
    return K.mean(f1)

def train(cli_args, log_dir):

    with open(cli_args.config, "r") as f:
        config = safe_load(f)
        
    if config is None:
        print("Please provide a config.")

    # Load Data + Labels
    DataLoader = getattr(data_loaders, config["data_loader"])

    train_data_generator = DataLoader(config["train_data_dir"], config)
    validation_data_generator = DataLoader(config["validation_data_dir"], config)

    # Training Callbacks
    checkpoint_filename = os.path.join(log_dir, "weights.{epoch:02d}.keras")
    model_checkpoint_callback = ModelCheckpoint(
        filepath=checkpoint_filename,
        save_best_only=True,
        verbose=1,
        monitor="val_accuracy"
    )

    tensorboard_callback = TensorBoard(log_dir=log_dir, write_images=True)
    csv_logger_callback = CSVLogger(os.path.join(log_dir, "log.csv"))
    early_stopping_callback = EarlyStopping(monitor='val_loss', min_delta=0, patience=10, verbose=1, mode="min")

    # Model Generation
    model_class = getattr(models, config["model"])
    model = model_class.create_model(train_data_generator.get_input_shape(), config)
    model.summary()

    optimizer = Adam(learning_rate=config["learning_rate"])
    # optimizer = RMSprop(lr=config["learning_rate"], rho=0.9, epsilon=1e-08, decay=0.95)
    # optimizer = SGD(lr=config["learning_rate"], decay=1e-6, momentum=0.9, clipnorm=1, clipvalue=10)
    model.compile(optimizer=optimizer,
                  loss="categorical_crossentropy",
                  metrics=["accuracy", Recall(), Precision(), f1_score])

    if cli_args.weights:
        model.load_weights(cli_args.weights)

    # Training
    history = model.fit(
        train_data_generator.get_data(),
        steps_per_epoch=train_data_generator.get_num_files(),
        epochs=config["num_epochs"],
        callbacks=[model_checkpoint_callback, tensorboard_callback, csv_logger_callback, early_stopping_callback],
        verbose=1,
        validation_data=validation_data_generator.get_data(should_shuffle=False),
        validation_steps=validation_data_generator.get_num_files()
    )

    file_path, _ = train_data_generator.images_label_pairs[0]
    start_time = time.time()
    img = train_data_generator.process_file(file_path)
    print(f"Tempo caricamento immagine: {time.time() - start_time:.4f} secondi")

    # Do evaluation on model with best validation accuracy
    best_epoch = np.argmax(history.history["val_accuracy"]) + 1
    print("Log files: ", log_dir)
    print("Best epoch: ", best_epoch)
    model_file_name = checkpoint_filename.replace("{epoch:02d}", "{:02d}".format(best_epoch))

    return model_file_name


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', dest='weights')
    parser.add_argument('--config', dest='config', default="config.yaml")
    cli_args = parser.parse_args()

    log_dir = os.path.join("logs", datetime.now().strftime("%Y-%m-%d-%H-%M-%S"))
    print("Logging to {}".format(log_dir))

    # copy models & config for later
    shutil.copytree("models", log_dir)  # creates the log_dir
    shutil.copy(cli_args.config, log_dir)

    model_file_name = train(cli_args, log_dir)

    DummyCLIArgs = namedtuple("DummyCLIArgs", ["model_dir", "config", "use_test_set"])
    evaluate(DummyCLIArgs(model_file_name, cli_args.config, False))