import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import os, sys
import catboost as cat
from sklearn.metrics import accuracy_score

import tensorflow as tf
from keras import backend as K
from keras.models import Model
from keras.layers import Dense, Dropout, Input, concatenate
from keras import optimizers

def generator_network(z, data_dim, min_num_neurones):
    x = Dense(min_num_neurones, activation='tanh')(z)
    x = Dense(min_num_neurones*2, activation='tanh')(x)
    x = Dense(min_num_neurones*4, activation='tanh')(x)
    x = Dense(min_num_neurones*8, activation='tanh')(x)
    x = Dense(data_dim)(x)
    return x

def discriminator_network(x, data_dim, min_num_neurones):
    x = Dense(min_num_neurones*4, activation='tanh')(x)
    x = Dense(min_num_neurones*2, activation='tanh')(x)
    x = Dense(min_num_neurones, activation='tanh')(x)
    x = Dense(1, activation='sigmoid')(x)
    return x

def define_models_GAN(z_dim, data_dim, min_num_neurones):
    """
    Put together the generator model and discriminator model (Define the full Generative Adversarial Network).

    Parameters:
    z_dim : int default = 1
        The dimmension of random noise
    data_dim : int
        The dimmension/size of the original Data (which will be genarated/faked)
    min_num_neurones : int
        The base/min count of neurones in each nn layer

    Return Value:
    generator_model : Model
        GAN generator Model (Keras model) G(z) -> x
    discriminator_model : Model
        Discriminator Model which will dertimine if a sample is fake or not. D(x)
    combined_model : model
        Generator + discriminator ==> (D(G(z)))
    """
    generator_input = Input(shape=(z_dim, ))
    generator_output = generator_network(generator_input, data_dim, min_num_neurones)

    #Generated sample (fake sample)
    discriminator_model_input = Input(shape=(data_dim,))
    discriminator_output = discriminator_network(discriminator_model_input, data_dim, min_num_neurones)

    #Generator
    generator_model = Model(inputs=[generator_input], outputs=[generator_output], name='generator')
    #Discriminator
    discriminator_model = Model(inputs=[discriminator_model_input],outputs=[discriminator_output],
                                       name='discriminator')

    #Full Network
    combined_output = discriminator_model(generator_model(generator_input))
    combined_model = Model(inputs=[generator_input], outputs=[combined_output], name='Full_Network')

    return generator_model, discriminator_model, combined_model

def get_batch(X, batch_size=1):
    """
    X : ndarray
        The input data to sample a into batch
    size : int (default = 1)
        Batch size
    """
    batch_ix = np.random.choice(len(X), batch_size, replace=False)
    return X[batch_ix]


def classifierAccuracy(X,g_z,n_samples):
    """
    Check how good are the generated samples using a catboost classifier. 50% accuracy
    means that the real samples are identical and the classifier can not differentiate.
    The classifier is trained with 0.5 n_real + 1/2 n_fake samples.

    X : ndarray
        The real samples
    g_z : ndarray
        The fake samples produced by a generator

    Rerurn Value:

    """
    y_fake = np.ones(n_samples)
    y_true = np.zeros(n_samples)

    n = n_samples//2
    x_train = np.vstack((X[:n,:],g_z[:n,:]))
    y_train = np.hstack((np.zeros(n),np.ones(n))) # fake : 1, real : 0

    x_test = np.vstack((X[n:,:],g_z[n:,:]))
    y_test = np.hstack((np.zeros(n),np.ones(n)))

    catb = cat.CatBoostClassifier(verbose=0,n_estimators=13,max_depth=5)
    catb.fit(x_train,y_train)

    pred = catb.predict(x_test)
    accuracy = accuracy_score(y_test,pred)

    return np.round(accuracy,decimals=3)

def kl_divergence(p, q):
    return np.sum(np.where(p != 0, p * np.log(p/q),0))

def training_steps(model_components):

    [train, data_dim,generator_model, discriminator_model, combined_model,rand_dim, nb_steps,
    batch_size, D_epochs, G_epochs,combined_loss, disc_loss_generated, disc_loss_real] = model_components

    for i in range(nb_steps):
        K.set_learning_phase(1)

        # train the discriminator
        for j in range(D_epochs):
            np.random.seed(i+j)
            z = np.random.normal(size=(batch_size, rand_dim))
            x = get_batch(train, batch_size)

            fake = generator_model.predict(z)

            #get discriminator loss on real samples (d_l_r) and Generated/faked (d_l_g)
            d_l_r = discriminator_model.train_on_batch(x, np.random.uniform(low=0.999, high=1.0, size=batch_size))
            d_l_g = discriminator_model.train_on_batch(fake, np.random.uniform(low=0.0, high=0.0001, size=batch_size))
            # d_l_r = discriminator_model.train_on_batch(x, np.random.uniform(low=0.0, high=0.0001, size=batch_size))
            # d_l_g = discriminator_model.train_on_batch(fake, np.random.uniform(low=0.999, high=1.0, size=batch_size))

        disc_loss_real.append(d_l_r)
        disc_loss_generated.append(d_l_g)

        #train generator
        loss = None
        for j in range(G_epochs):
            np.random.seed(i+j)
            z = np.random.normal(size=(batch_size, rand_dim))

            # loss = combined_model.train_on_batch(z, np.random.uniform(low=0.0, high=0.0001, size=batch_size))
            loss = combined_model.train_on_batch(z, np.random.uniform(low=0.999, high=1.0, size=batch_size))

        combined_loss.append(loss)

        # Checkpoint : get the lossess summery (for Generator and discriminator)
        if i % 10 == 0:
            K.set_learning_phase(0)
            test_size = len(train)

            z = np.random.normal(size=(test_size, rand_dim))
            g_z = generator_model.predict(z)

            acc = classifierAccuracy(train,g_z,test_size)

            print("Ephoc : {} , combined_loss : {} , classifier_accuracy : {}".format(i,loss,acc))

    return [combined_loss, disc_loss_generated, disc_loss_real]

def adversarial_training_GAN(arguments, train):

    [rand_noise_dim, nb_steps, batch_size,D_epochs, G_epochs, learning_rate, min_num_neurones] = arguments

    data_dim = train.shape[1]

    # define network models
    K.set_learning_phase(1) # 1 = train

    generator_model, discriminator_model, combined_model = define_models_GAN(rand_noise_dim, data_dim, min_num_neurones)

    # compile models
    adam = optimizers.Adam(lr=learning_rate, beta_1=0.5, beta_2=0.9)

    generator_model.compile(optimizer=adam, loss='binary_crossentropy')
    discriminator_model.compile(optimizer=adam, loss='binary_crossentropy')
    discriminator_model.trainable = False
    combined_model.compile(optimizer=adam, loss='binary_crossentropy')


    print(generator_model.summary())
    print(discriminator_model.summary())
    print(combined_model.summary())

    combined_loss, disc_loss_generated, disc_loss_real = [], [], []

    model_components = [train, data_dim,generator_model, discriminator_model, combined_model,
                        rand_noise_dim, nb_steps, batch_size, D_epochs, G_epochs,
                        combined_loss, disc_loss_generated, disc_loss_real ]

    [combined_loss, disc_loss_generated, disc_loss_real] = training_steps(model_components)

    return dict({"generator_model":generator_model,"discriminator_model":discriminator_model,\
            "combined_model":combined_model,"combined_loss":combined_loss,\
            "disc_loss_generated":disc_loss_generated,"disc_loss_real": disc_loss_real})