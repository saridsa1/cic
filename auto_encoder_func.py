"""Helper classes and functions for auto_encoder_model.py"""
import tensorflow as tf
import baseline_model_func
import chat_model_func
import numpy as np
import pickle
import squad_dataset_tools as sdt

class AutoEncoder:
    """Auto-encoder model built in Tensorflow. Encodes English sentences as points
    in n-dimensional space(as codes) using an encoder RNN, then converts from that space
    back to the original sentence using a decoder RNN. Can be used on arbitrary input
    sequences other than English sentences. Represents input tokens as indices and
    learns an embedding per index."""
    def __init__(self, word_embedding_size, vocab_size, rnn_size, max_message_size,
                 encoder=True, decoder=True, learning_rate=None, save_dir=None, load_from_save=False):
        self.word_embedding_size = word_embedding_size
        self.encoder = encoder
        self.decoder = decoder
        self.rnn_size = rnn_size
        self.max_message_size = max_message_size
        self.vocab_size = vocab_size
        self.learning_rate = learning_rate
        self.save_dir = save_dir

        assert encoder or decoder

        self.tf_message = tf.placeholder(dtype=tf.int32, shape=[None, self.max_message_size], name='input_message')
        self.tf_latent = tf.placeholder(dtype=tf.float32, shape=[None, self.rnn_size], name='latent_embedding')
        self.tf_keep_prob = tf.placeholder_with_default(1.0, (), name='keep_prob')
        with tf.variable_scope('LEARNED_EMBEDDINGS'):
            self.tf_learned_embeddings = tf.get_variable('learned_embeddings',
                                                         shape=[self.vocab_size, self.word_embedding_size],
                                                         initializer=tf.contrib.layers.xavier_initializer())
        if self.encoder:
            self.tf_latent_message, self.tf_latent_mean, self.tf_latent_log_std \
                = self.build_encoder(self.tf_message, self.tf_keep_prob)
        if self.decoder:
            if self.encoder:
                decoder_input = self.tf_latent_message
            else:
                decoder_input = self.tf_latent
            self.tf_message_prediction, self.tf_message_log_prob, self.tf_message_prob \
                = self.build_decoder(decoder_input)
        if self.decoder and self.encoder and self.learning_rate is not None:
            self.train_op, self.tf_total_loss, self.tf_kl_loss \
                = self.build_trainer(self.tf_message_log_prob, self.tf_message,
                                     self.tf_latent_mean, self.tf_latent_log_std, self.learning_rate)

            with tf.name_scope("SAVER"):
                self.saver = tf.train.Saver(var_list=tf.trainable_variables(), max_to_keep=10)
        init = tf.global_variables_initializer()
        self.sess = tf.InteractiveSession()
        self.sess.run(init)
        if load_from_save:
            print('Loading from save...')
            self.load_scope_from_save(save_dir, self.sess, 'LEARNED_EMBEDDINGS')
            if self.encoder:
                self.load_scope_from_save(save_dir, self.sess, 'MESSAGE_ENCODER')
            if self.decoder:
                self.load_scope_from_save(save_dir, self.sess, 'MESSAGE_DECODER')

    def encode(self, np_message, batch_size=None):
        """Converts sentences encoded as numpy arrays to points in a latent space."""
        assert self.encoder
        if batch_size is None:
            batch_size = np_message.shape[0]
        all_val_latent_batches = []
        val_batch_gen = chat_model_func.BatchGenerator(np_message, batch_size)
        for batch_index, np_message_batch in enumerate(val_batch_gen.generate_batches()):
            np_val_batch_latent = self.sess.run(self.tf_latent_message, feed_dict={self.tf_message: np_message_batch})
            all_val_latent_batches.append(np_val_batch_latent)
        np_latent_message = np.concatenate(all_val_latent_batches, axis=0)
        return np_latent_message

    def decode(self, np_latent, batch_size=None):
        """Converts points in a latent space to sentences encoded as numpy arrays."""
        assert self.decoder and not self.encoder
        if batch_size is None:
            batch_size = np_latent.shape[0]
        all_val_message_batches = []
        val_batch_gen = chat_model_func.BatchGenerator(np_latent, batch_size)
        for batch_index, np_latent_batch in enumerate(val_batch_gen.generate_batches()):
            np_val_batch_reconstruct = self.sess.run(self.tf_message_prediction, feed_dict={self.tf_latent: np_latent_batch})
            all_val_message_batches.append(np_val_batch_reconstruct)
        np_val_message_reconstruct = np.concatenate(all_val_message_batches, axis=0)
        return np_val_message_reconstruct

    def reconstruct(self, np_input, batch_size=None):
        """Converts sentences into a latent space format, then reconstructs them.
        Returns reconstructions of the input sentences, formatted as numpy arrays."""
        assert self.encoder and self.decoder
        if batch_size is None:
            batch_size = np_input.shape[0]
        all_val_message_batches = []
        val_batch_gen = chat_model_func.BatchGenerator(np_input, batch_size)
        for batch_index, np_message_batch in enumerate(val_batch_gen.generate_batches()):
            np_val_batch_reconstruct = self.sess.run(self.tf_message_prediction, feed_dict={self.tf_message: np_message_batch})
            all_val_message_batches.append(np_val_batch_reconstruct)
        np_val_message_reconstruct = np.concatenate(all_val_message_batches, axis=0)
        return np_val_message_reconstruct

    def train(self, np_input, num_epochs, batch_size, keep_prob=1.0):
        """Trains on examples from np_input for num_epoch epochs,
        by dividing the data into batches of size batch_size."""
        examples_per_print = 200
        for epoch in range(num_epochs):
            train_batch_gen = chat_model_func.BatchGenerator(np_input, batch_size)
            all_train_message_batches = []
            per_print_batch_losses = []
            for batch_index, np_message_batch in enumerate(train_batch_gen.generate_batches()):
                _, batch_loss, np_batch_message_reconstruct = self.sess.run([self.train_op, self.tf_total_loss, self.tf_message_prediction],
                                                                       feed_dict={self.tf_message: np_message_batch,
                                                                                  self.tf_keep_prob: keep_prob})
                all_train_message_batches.append(np_batch_message_reconstruct)
                per_print_batch_losses.append(batch_loss)
                if batch_index % examples_per_print == 0:
                    print('Batch loss: %s' % np.mean(per_print_batch_losses))
                    per_print_batch_losses = []
            self.saver.save(self.sess, self.save_dir, global_step=epoch)
        np_train_message_reconstruct = np.concatenate(all_train_message_batches, axis=0)
        return np_train_message_reconstruct

    def build_encoder(self, tf_message, tf_keep_prob):
        """Build encoder portion of autoencoder in Tensorflow."""
        with tf.variable_scope('MESSAGE_ENCODER'):
            tf_message_embs = tf.nn.embedding_lookup(self.tf_learned_embeddings, tf_message, name='message_embeddings')
            tf_message_embs_dropout = tf.nn.dropout(tf_message_embs, tf_keep_prob)

            message_lstm = tf.contrib.rnn.LSTMCell(num_units=self.rnn_size)
            tf_message_outputs, tf_message_state = tf.nn.dynamic_rnn(message_lstm, tf_message_embs_dropout, dtype=tf.float32)
            tf_last_output = tf_message_outputs[:, -1, :]
            tf_last_output_dropout = tf.nn.dropout(tf_last_output, tf_keep_prob)

        tf_latent_mean, _, _ = baseline_model_func.create_dense_layer(tf_last_output_dropout, self.rnn_size, self.rnn_size, name='latent_mean')
        tf_latent_log_std, _, _ = baseline_model_func.create_dense_layer(tf_last_output_dropout, self.rnn_size, self.rnn_size, name='latent_std')
            #tf_epsilon = tf.random_normal(tf.shape(tf_latent_mean), stddev=1, mean=0)
            #tf_sampled_latent = tf_latent_mean + tf.exp(tf_latent_log_std) * tf_epsilon
        return tf_last_output_dropout, tf_latent_mean, tf_latent_log_std

    def build_decoder(self, tf_decoder_input):
        """Build decoder portion of autoencoder in Tensorflow."""
        with tf.variable_scope('MESSAGE_DECODER'):
            tf_message_final_output_tile = tf.tile(tf.reshape(tf_decoder_input, [-1, 1, self.rnn_size]),
                                                   [1, self.max_message_size, 1])

            response_lstm = tf.contrib.rnn.LSTMCell(num_units=self.rnn_size)
            tf_response_outputs, tf_response_state = tf.nn.dynamic_rnn(response_lstm, tf_message_final_output_tile,
                                                                       dtype=tf.float32)
            output_weight = tf.get_variable('output_weight',
                                            shape=[self.rnn_size, self.word_embedding_size],
                                            initializer=tf.contrib.layers.xavier_initializer())
            output_bias = tf.get_variable('output_bias',
                                          shape=[self.word_embedding_size],
                                          initializer=tf.contrib.layers.xavier_initializer())
            with tf.name_scope('tf_message_log_probabilities'):
                tf_response_outputs_reshape = tf.reshape(tf_response_outputs, [-1, self.rnn_size])
                tf_response_output_embs = tf.matmul(tf_response_outputs_reshape, output_weight) + output_bias
                print(tf_response_output_embs.get_shape())
                tf_flat_message_log_prob = tf.matmul(tf_response_output_embs, self.tf_learned_embeddings, transpose_b=True)
                tf_message_log_prob = tf.reshape(tf_flat_message_log_prob, [-1, self.max_message_size, self.vocab_size])

            tf_message_prob = tf.nn.softmax(tf_message_log_prob, name='message_probabilities')

            tf_message_prediction = tf.argmax(tf_message_prob, axis=2)

        return tf_message_prediction, tf_message_log_prob, tf_message_prob

    def build_trainer(self, tf_message_log_prob, tf_message, tf_latent_mean, tf_latent_log_std, learning_rate):
        """Calculate loss function and construct optimizer op
        for 'tf_message_log_prob' prediction and 'tf_message' label."""
        with tf.variable_scope('LOSS'):
            tf_losses = tf.nn.sparse_softmax_cross_entropy_with_logits(logits=tf_message_log_prob,
                                                                       labels=tf_message,
                                                                       name='word_losses')
            # Add KL loss
            tf_kl_loss = .5 * (1 + tf_latent_log_std - tf.square(tf_latent_mean) - tf.exp(tf_latent_log_std))

            with tf.name_scope('total_loss'):
                tf_total_loss = tf.reduce_mean(tf_losses) + tf.reduce_mean(tf_kl_loss)

        train_op = tf.train.AdamOptimizer(learning_rate).minimize(tf_total_loss)
        return train_op, tf_total_loss, tf_kl_loss

    def load_scope_from_save(self, save_dir, sess, scope):
        """Load the encoder model variables from checkpoint in save_dir.
        Store them in session sess."""
        vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=scope)
        assert len(vars) > 0
        baseline_model_func.restore_model_from_save(save_dir,
                                                    var_list=vars, sess=sess)

    def __call__(self, np_input):
        pass