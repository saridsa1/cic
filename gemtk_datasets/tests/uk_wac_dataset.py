""" Example driver program for constructing a UKWacDataset object. """
from gemtk_datasets.uk_wac_dataset import UKWacDataset
import config
import os
import numpy as np

ukwac_path = '/data2/arogers/Corpora/En/UkWac/Plain-txt/ukwac_subset_100M.txt'
result_path = os.path.join(config.DATA_DIR, 'ukwac')
print('Loading dataset...')
ukwac = UKWacDataset(ukwac_path, result_save_path=result_path, max_length=15, regenerate=False)
print('Number of numpy messages in dataset: %s' % ukwac.np_messages.shape[0])
print('Vocabulary size: %s' % len(ukwac.get_vocabulary()[0]))

m = len(ukwac)
assert m == len(ukwac.messages)

for index in range(m):
    each_example = ukwac[index]
    each_np_message = np.reshape(each_example['message'], newshape=(-1, 15))
    each_reconstructed_message = ukwac.convert_numpy_to_strings(each_np_message)[0]

    each_message = ukwac.messages[index]
    if index < 10:
        print(each_message)

    if (each_message) != each_reconstructed_message:
        print('Error:')
        print(each_message)
        print(each_reconstructed_message)
        raise AssertionError('Reconstructed strings must be same as original strings')

print('Strings converted back from numpy match original strings.')