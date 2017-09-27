import gmtk
import tensorflow as tf
import cornell_movie_dialogues as cmd
import numpy as np
import squad_dataset_tools as sdt


class AutoEncoder(gmtk.GenericModel):
    def __init__(self, vocab_size, max_len=20, rnn_size=500, emb_size=200, **kwargs):
        self.vocab_size = vocab_size
        self.max_len = max_len
        self.rnn_size = rnn_size
        self.emb_size = emb_size

        # Define parameters for build before calling main constructor
        super().__init__(**kwargs)

    def build(self):
        # Load specific scopes from save - if not here, entire Graph is loaded
        self.load_scopes = ['ENCODER', 'DECODER']

        # Build model with separate decoders for training and prediction
        self.inputs['message'] \
            = tf.placeholder(dtype=tf.int32, shape=(None, self.max_len), name='message')
        self.inputs['code'] \
            = tf.placeholder(dtype=tf.float32, shape=(None, self.rnn_size), name='code')
        self.outputs['embeddings'] \
            = tf.get_variable('embeddings', shape=(self.vocab_size, self.emb_size),
                              initializer=tf.contrib.layers.xavier_initializer())
        self.inputs['keep prob'] = tf.placeholder_with_default(1.0, shape=(), name='keep_prob')

        self.outputs['code'] \
            = self.build_encoder(self.inputs['message'], self.outputs['embeddings'], self.inputs['keep prob'])

        # For training
        with tf.variable_scope('DECODER'):
            self.outputs['train_prediction'], tf_train_logits, self.outputs['train_probability'] \
                = self.build_decoder(self.outputs['code'], self.outputs['embeddings'], tf_labels=self.inputs['message'])

        with tf.variable_scope('LOSS'):
            self.loss = self.build_trainer(tf_train_logits, self.inputs['message'])

        # For prediction
        with tf.variable_scope('DECODER', reuse=True):
            self.outputs['prediction'], _, self.outputs['probability'] \
                = self.build_decoder(self.inputs['code'], self.outputs['embeddings'], tf_labels=None)

    def build_encoder(self, tf_message, tf_embeddings, tf_keep_prob, reverse_input_messages=True):
        """Build encoder portion of autoencoder."""
        tf_message_embs = tf.nn.embedding_lookup(tf_embeddings, tf_message)
        if reverse_input_messages:
            tf_message_embs = tf.reverse(tf_message_embs, axis=[1], name='reverse_message_embs')
        tf_message_embs_dropout = tf.nn.dropout(tf_message_embs, tf_keep_prob)
        message_lstm = tf.contrib.rnn.LSTMCell(num_units=self.rnn_size)
        tf_message_outputs, tf_message_state = tf.nn.dynamic_rnn(message_lstm, tf_message_embs_dropout, dtype=tf.float32)
        tf_last_output = tf_message_outputs[:, -1, :]
        tf_last_output_dropout = tf.nn.dropout(tf_last_output, tf_keep_prob)

        return tf_last_output_dropout

    def build_decoder(self, tf_latent_input, tf_embeddings, tf_labels=None):
        """Build decoder portion of autoencoder in Tensorflow."""
        tf_latent_input_shape = tf.shape(tf_latent_input)
        m = tf_latent_input_shape[0]

        output_weight = tf.get_variable('output_weight',
                                        shape=[self.rnn_size, self.emb_size],
                                        initializer=tf.contrib.layers.xavier_initializer())
        output_bias = tf.get_variable('output_bias',
                                      shape=[self.emb_size],
                                      initializer=tf.contrib.layers.xavier_initializer())

        tf_go_token = tf.get_variable('go_token', shape=[1, self.emb_size])
        tf_go_token_tile = tf.tile(tf_go_token, [m, 1])

        tf_label_embs = None
        if tf_labels is not None:
            tf_label_embs = tf.nn.embedding_lookup(tf_embeddings, tf_labels)

        response_lstm = tf.contrib.rnn.LSTMCell(num_units=self.rnn_size)
        tf_hidden_state = response_lstm.zero_state(m, tf.float32)
        all_word_logits = []
        all_word_probs = []
        all_word_predictions = []
        for i in range(self.max_len):
            if i == 0:
                tf_teacher_signal = tf_go_token_tile  # give model go token on first step
            else:
                if tf_labels is not None:
                    tf_teacher_signal = tf_label_embs[:, i - 1, :]  # @i=1, selects first label word
                else:
                    tf_teacher_signal = tf_word_prediction_embs  # available only for i > 0

            tf_decoder_input = tf.concat([tf_latent_input, tf_teacher_signal], axis=1)

            tf_output, tf_hidden_state = response_lstm(tf_decoder_input, tf_hidden_state)
            tf_word_emb = tf.tanh(tf.matmul(tf_output, output_weight) + output_bias)
            tf_word_logits = tf.matmul(tf_word_emb, tf_embeddings, transpose_b=True)
            tf_word_prob = tf.nn.softmax(tf_word_logits)
            tf_word_prediction = tf.argmax(tf_word_logits, axis=1)

            tf_word_prediction_embs = tf.nn.embedding_lookup(tf_embeddings, tf_word_prediction)

            all_word_logits.append(tf_word_logits)
            all_word_probs.append(tf_word_prob)
            all_word_predictions.append(tf_word_prediction)

        with tf.name_scope('decoder_outputs'):
            tf_message_logits = tf.stack(all_word_logits, axis=1)
            tf_message_prob = tf.stack(all_word_probs, axis=1)
            tf_message_prediction = tf.stack(all_word_predictions, axis=1)

        return tf_message_prediction, tf_message_logits, tf_message_prob

    def build_trainer(self, tf_message_logits, tf_message):
        """Calculate loss function and construct optimizer op
        for 'tf_message_log_prob' prediction and 'tf_message' label."""
        tf_losses = tf.nn.sparse_softmax_cross_entropy_with_logits(logits=tf_message_logits,
                                                                   labels=tf_message,
                                                                   name='word_losses')
        tf_output_loss = tf.reduce_mean(tf_losses)

        return tf_output_loss

    def encode(self, dataset):
        # Convert to dictionary if numpy input
        if isinstance(dataset, np.ndarray):
            dataset = {'message': dataset}

        results = self.predict(dataset, output_tensor_names=['code'])
        return results['code']

    def decode(self, dataset):
        # Convert to dictionary if numpy input
        if isinstance(dataset, np.ndarray):
            dataset = {'code': dataset}

        results = self.predict(dataset, output_tensor_names=['prediction'])

        return results['prediction']

    # def action_per_batch(self, input_batch_dict, output_batch_dict, epoch_index, batch_index, is_training, **kwargs):
    #     if batch_index % 200 == 0:
    #         print(batch_index)

if __name__ == '__main__':
    cmd_dataset = cmd.CornellMovieDialoguesDataset(max_message_length=20, num_examples=100)

    train_cmd, val_cmd = cmd_dataset.split(fraction=0.9)

    print('Number of training examples: %s' % len(train_cmd))
    print('Number of validation examples: %s' % len(val_cmd))

    token_to_id, id_to_token = cmd_dataset.get_vocabulary()

    autoencoder = AutoEncoder(len(token_to_id), tensorboard_name='gmae', save_dir='./data/autoencoder/first/')

    autoencoder.train(train_cmd, output_tensor_names=['train_prediction'],
                      num_epochs=100, batch_size=20, verbose=False)

    predictions = autoencoder.decode(autoencoder.encode(train_cmd))

    # Here, I need to convert predictions back to English and print
    reconstructed_messages = sdt.convert_numpy_array_to_strings(predictions, id_to_token,
                                                                stop_token=cmd_dataset.stop_token,
                                                                keep_stop_token=True)

    for i in range(10):
        print(' '.join(cmd_dataset.messages[train_cmd.indices[i]]) + " | " + reconstructed_messages[i])

    num_train_correct = 0
    for i in range(len(reconstructed_messages)):
        original_message = ' '.join(cmd_dataset.messages[train_cmd.indices[i]])
        if original_message == reconstructed_messages[i]:
            num_train_correct += 1

    print('Train EM accuracy: %s' % (num_train_correct / len(reconstructed_messages)))

    val_predictions = autoencoder.decode(autoencoder.encode(val_cmd))

    val_reconstructed_messages = sdt.convert_numpy_array_to_strings(val_predictions, id_to_token,
                                                                    stop_token=cmd_dataset.stop_token,
                                                                    keep_stop_token=True)

    print()

    for i in range(10):
        print(' '.join(cmd_dataset.messages[val_cmd.indices[i]]) + " | " + val_reconstructed_messages[i])

    num_val_correct = 0
    for i in range(len(val_reconstructed_messages)):
        original_message = ' '.join(cmd_dataset.messages[val_cmd.indices[i]])
        if original_message == val_reconstructed_messages[i]:
            num_val_correct += 1

    print('Validation EM accuracy: %s' % (num_val_correct / len(val_reconstructed_messages)))

    # print('Testing the autoencoder...')
    # # Test autoencoder using stdin
    # while True:
    #     message = input('Message: ')
    #     np_message = cmd.construct_numpy_from_messages([message.split()])






