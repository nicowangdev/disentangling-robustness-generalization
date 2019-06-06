import os
import sys

sys.path.insert(1, os.path.dirname(os.path.realpath(__file__)) + '/../')
from common import utils
from common.log import log
from common import paths
import common.torch
import common.numpy
import models

import torch
import math
import numpy
import argparse
import sklearn.decomposition
import sklearn.neighbors
import terminaltables


if utils.display():
    from common import plot


class TestAttackDecoderClassifier:
    """
    Test a trained classifier.
    """

    def __init__(self, args=None):
        """
        Initialize.

        :param args: optional arguments if not to use sys.argv
        :type args: [str]
        """

        self.args = None
        """ Arguments of program. """

        parser = self.get_parser()
        if args is not None:
            self.args = parser.parse_args(args)
        else:
            self.args = parser.parse_args()

        self.test_images = None
        """ (numpy.ndarray) Test images. """

        self.train_images = None
        """ (numpy.ndarray) Train images. """

        self.test_theta = None
        """ (numpy.ndarray) Transformation parameters. """

        self.train_theta = None
        """ (numpy.ndarra) Transformation parameters, i.e. latent codes. """

        self.perturbations = None
        """ (numpy.ndarray) Perturbations per test image. """

        self.test_codes = None
        """ (numpy.ndarray) Test codes."""

        self.success = None
        """ (numpy.ndarray) Success indicator for perturbations."""

        self.norms = [1, 2, float('inf')]
        """ ([float]) Norms to evaluate. """

        self.results = []
        """ (dict) Dictionary containing all statistics. """

        for n in range(len(self.norms)):
            self.results.append(dict())

        self.N_font = None
        """ (int) Number of fonts. """

        self.N_class = None
        """ (int) Number of classes. """

        self.N_attempts = None
        """ (int) Numbe rof attack attempts. """

        self.theta_images = None
        """ (numpy.ndarray) WIll hold images. """

        self.perturbation_images = None
        """ (numpy.ndarray) Will hold images for perturbations. """

        self.perturbation_codes = None
        """ (numpy.ndarray) Perturbation codes. """

        self.perturbation_theta = None
        """ (numpy.ndarray) Perturbation transformations. """

        self.model = None
        """ (Decoder) Decoder. """

        self.pca = None
        """ (sklearn.decomposition.IncrementalPCA) PCA to make nearest neighbor more efficient. """

        self.neighbors = None
        """ (sklearn.neighbors.NearestNeighbors) Nearest neighbor model. """

        log('-- ' + self.__class__.__name__)
        for key in vars(self.args):
            log('[Testing] %s=%s' % (key, str(getattr(self.args, key))))

    def get_parser(self):
        """
        Get parser.

        :return: parser
        :rtype: argparse.ArgumentParser
        """

        parser = argparse.ArgumentParser(description='Test attacks on classifier.')
        parser.add_argument('-database_file', default=paths.database_file(), help='HDF5 file containing font prototype images.', type=str)
        parser.add_argument('-test_images_file', default=paths.test_images_file(), help='HDF5 file containing dataset.', type=str)
        parser.add_argument('-train_images_file', default=paths.train_images_file(), help='HDF5 file containing dataset.', type=str)
        parser.add_argument('-test_theta_file', default=paths.test_theta_file(), help='HDF5 file containing dataset.', type=str)
        parser.add_argument('-train_theta_file', default=paths.train_theta_file(), help='HDF5 file containing dataset.', type=str)
        parser.add_argument('-test_codes_file', default=paths.test_codes_file(), help='HDF5 file containing labels.', type=str)
        parser.add_argument('-accuracy_file', default=paths.results_file('classifier/accuracy'), help='Correctly classified test samples of classifier.', type=str)
        parser.add_argument('-perturbations_file', default=paths.results_file('decoder/perturbations'), help='HDF5 file containing perturbations.', type=str)
        parser.add_argument('-success_file', default=paths.results_file('decoder/success'), help='HDF5 file indicating attack success.', type=str)
        parser.add_argument('-plot_directory', default=paths.experiment_dir('decoder'), help='Path to PNG plot file for success rate.', type=str)
        parser.add_argument('-results_file', default='', help='Path to pickled results file.', type=str)
        parser.add_argument('-batch_size', default=128, help='Batch size of attack.', type=int)
        parser.add_argument('-plot_manifolds', default=False, action='store_true', help='Whether to plot manifolds.')
        parser.add_argument('-no_gpu', dest='use_gpu', action='store_false')

        return parser

    def load_data(self):
        """
        Load data and model.
        """

        self.test_images = utils.read_hdf5(self.args.test_images_file).astype(numpy.float32)
        log('[Testing] read %s' % self.args.test_images_file)

        if len(self.test_images.shape) <= 3:
            self.test_images = numpy.expand_dims(self.test_images, axis=3)
            log('[Testing] no color images, adjusted size')

        self.train_images = utils.read_hdf5(self.args.train_images_file).astype(numpy.float32)
        # !
        self.train_images = self.train_images.reshape((self.train_images.shape[0], -1))
        log('[Testing] read %s' % self.args.train_images_file)

        self.test_theta = utils.read_hdf5(self.args.test_theta_file).astype(numpy.float32)
        log('[Testing] read %s' % self.args.test_theta_file)

        self.train_theta = utils.read_hdf5(self.args.train_theta_file).astype(numpy.float32)
        log('[Testing] read %s' % self.args.train_theta_file)

        self.test_codes = utils.read_hdf5(self.args.test_codes_file).astype(int)
        log('[Testing] read %s' % self.args.test_codes_file)

        self.accuracy = utils.read_hdf5(self.args.accuracy_file)
        log('[Testing] read %s' % self.args.accuracy_file)

        self.perturbations = utils.read_hdf5(self.args.perturbations_file).astype(numpy.float32)
        self.N_attempts = self.perturbations.shape[0]

        # First, repeat relevant data.
        self.perturbation_theta = numpy.repeat(self.test_theta[:self.perturbations.shape[1]], self.N_attempts, axis=0)
        self.perturbation_codes = numpy.repeat(self.test_codes[:self.perturbations.shape[1]], self.N_attempts, axis=0)
        self.accuracy = numpy.repeat(self.accuracy[:self.perturbations.shape[1]], self.N_attempts, axis=0)

        # Then, reshape the perturbations!
        self.perturbations = numpy.swapaxes(self.perturbations, 0, 1)
        self.perturbations = self.perturbations.reshape((self.perturbations.shape[0] * self.perturbations.shape[1], -1))
        log('[Testing] read %s' % self.args.perturbations_file)

        self.success = utils.read_hdf5(self.args.success_file)
        self.success = numpy.swapaxes(self.success, 0, 1)
        self.success = self.success.reshape((self.success.shape[0] * self.success.shape[1]))
        log('[Testing] read %s' % self.args.success_file)

        database = utils.read_hdf5(self.args.database_file)
        log('[Testing] read %s' % self.args.database_file)

        self.N_font = database.shape[0]
        self.N_class = database.shape[1]
        N_theta = self.test_theta.shape[1]
        log('[Testing] using %d N_theta' % N_theta)

        database = database.reshape((database.shape[0] * database.shape[1], database.shape[2], database.shape[3]))
        database = torch.from_numpy(database)
        if self.args.use_gpu:
            database = database.cuda()
        database = torch.autograd.Variable(database, False)

        self.model = models.AlternativeOneHotDecoder(database, self.N_font, self.N_class, N_theta)
        self.model.eval()

    def compute_images(self):
        """
        Compute images through decoder.
        """

        assert self.model.training is False

        num_batches = int(math.ceil(self.perturbations.shape[0]/self.args.batch_size))
        for b in range(num_batches):
            b_start = b * self.args.batch_size
            b_end = min((b + 1) * self.args.batch_size, self.perturbations.shape[0])

            batch_fonts = self.perturbation_codes[b_start: b_end, 1]
            batch_classes = self.perturbation_codes[b_start: b_end, 2]
            batch_code = numpy.concatenate((common.numpy.one_hot(batch_fonts, self.N_font), common.numpy.one_hot(batch_classes, self.N_class)), axis=1).astype(numpy.float32)

            batch_code = common.torch.as_variable(batch_code, self.args.use_gpu)
            batch_theta = common.torch.as_variable(self.perturbation_theta[b_start: b_end], self.args.use_gpu)
            theta_images = self.model(batch_code, batch_theta)

            batch_perturbation = common.torch.as_variable(self.perturbations[b_start: b_end], self.args.use_gpu)
            perturbation_images = self.model(batch_code, batch_perturbation)

            if b % 100:
                log('[Testing] %d' % b)

            theta_images = numpy.squeeze(numpy.transpose(theta_images.cpu().detach().numpy(), (0, 2, 3, 1)))
            self.theta_images = common.numpy.concatenate(self.theta_images, theta_images)

            perturbation_images = numpy.squeeze(numpy.transpose(perturbation_images.cpu().detach().numpy(), (0, 2, 3, 1)))
            self.perturbation_images = common.numpy.concatenate(self.perturbation_images, perturbation_images)

        self.theta_images = self.theta_images.reshape((self.theta_images.shape[0], -1))
        self.perturbation_images = self.perturbation_images.reshape((self.perturbation_images.shape[0], -1))

    def compute_nearest_neighbors(self, images):
        """
        Compute distances in image and latent space.

        :param images: images to get nearest neighbors for
        :type images: numpy.ndarray
        :param norm: norm to use
        :type norm: float
        """

        fit = 100000
        if self.pca is None:
            self.pca = sklearn.decomposition.IncrementalPCA(n_components=20)
            self.pca.fit(self.train_images[:fit])
            log('[Testing] fitted PCA')
        if self.neighbors is None:
            data = self.pca.transform(self.train_images)
            self.neighbors = sklearn.neighbors.NearestNeighbors(n_neighbors=10, algorithm='kd_tree')
            self.neighbors.fit(data[:fit])
            log('[Testing] fitted nearest neighbor')

        data = self.pca.transform(images)
        _, indices = self.neighbors.kneighbors(data)
        return indices

    def compute_statistics(self):
        """
        Compute statistics based on distances.
        """

        # That's the basis for all computation as we only want to consider successful attacks
        # on test samples that were correctly classified.
        raw_overall_success = numpy.logical_and(self.success >= 0, self.accuracy)

        # Important check, for on-manifold attack this will happen if the manifold is small and the model very accurate!
        if not numpy.any(raw_overall_success):
            for n in range(len(self.norms)):
                for type in ['raw_success', 'raw_iteration', 'raw_average', 'raw_image']:
                    self.results[n][type] = 0
                for type in ['raw_class_success', 'raw_class_average', 'raw_class_image']:
                    self.results[n][type] = numpy.zeros((self.N_class))
            if self.args.results_file:
                utils.write_pickle(self.args.results_file, self.results)
                log('[Testing] wrote %s' % self.args.results_file)
            log('[Testing] no successful attacks found, no plots')
            return

        #
        # Compute nearest neighbor statistics in image space.
        #

        if self.args.plot_directory and self.args.plot_manifolds and utils.display():
            log('[Testing] computing nearest neighbor ...')
            nearest_neighbors_indices = self.compute_nearest_neighbors(self.perturbation_images[raw_overall_success])
            pure_perturbations = self.theta_images[raw_overall_success] - self.perturbation_images[raw_overall_success]
            pure_perturbations_norm = numpy.linalg.norm(pure_perturbations, ord=2, axis=1)
            for k in range(10):
                direction = self.perturbation_images[raw_overall_success] - self.train_images[nearest_neighbors_indices[:, k]]
                direction_norm = numpy.linalg.norm(direction, ord=2, axis=1)
                dot_products = numpy.einsum('ij,ij->i', direction, pure_perturbations)
                dot_product_norms = numpy.multiply(pure_perturbations_norm, direction_norm)
                dot_products, dot_product_norms = dot_products[dot_product_norms > 10**-8], dot_product_norms[dot_product_norms > 10**-8]
                dot_products /= dot_product_norms
                dot_products = numpy.degrees(numpy.arccos(dot_products))

                # matplotlib's hsitogram plots give weird error if there are NaN values, so simple check:
                if dot_products.shape[0] > 0 and not numpy.any(dot_products != dot_products):
                    print(dot_products)
                    plot_file = os.path.join(self.args.plot_directory, 'dot_products_nn%d' % k)
                    plot.histogram(plot_file, dot_products, 100, xmin=numpy.min(dot_products), xmax=numpy.max(dot_products),
                                  title='Dot Products Between Adversarial Perturbations and Direction to Nearest Neighbor %d' % k,
                                  xlabel='Dot Product', ylabel='Count')
                    log('[Testing] wrote %s' % plot_file)

        #
        # We compute some simple statistics:
        # - raw success rate: fraction of successful attack without considering epsilon
        # - corrected success rate: fraction of successful attacks within epsilon-ball
        # - raw average perturbation: average distance to original samples (for successful attacks)
        # - corrected average perturbation: average distance to original samples for perturbations
        #   within epsilon-ball (for successful attacks).
        # These statistics can also be computed per class.
        # And these statistics are computed with respect to three norms.

        if self.args.plot_directory and utils.display():
            iterations = self.success[raw_overall_success]
            x = numpy.arange(numpy.max(iterations) + 1)
            y = numpy.bincount(iterations)
            plot_file = os.path.join(self.args.plot_directory, 'iterations')
            plot.bar(plot_file, x, y,
                    title='Distribution of Iterations of Successful Attacks', xlabel='Number of Iterations', ylabel='Count')
            log('[Testing] wrote %s' % plot_file)

        for n in range(len(self.norms)):
            norm = self.norms[n]
            delta = numpy.linalg.norm(self.perturbation_theta - self.perturbations, norm, axis=1)
            image_delta = numpy.linalg.norm(self.theta_images - self.perturbation_images, norm, axis=1)

            if self.args.plot_directory and utils.display():
                plot_file = os.path.join(self.args.plot_directory, 'distances_l%g' % norm)
                plot.histogram(plot_file, delta[raw_overall_success], 50, title='Distribution of $L_{%g}$ Distances of Successful Attacks' % norm,
                              xlabel='Distance', ylabel='Count')
                log('[Testing] wrote %s' % plot_file)

            #debug_accuracy = numpy.sum(self.accuracy) / self.accuracy.shape[0]
            #debug_attack_fraction = numpy.sum(raw_overall_success) / numpy.sum(self.success >= 0)
            #debug_test_fraction = numpy.sum(raw_overall_success) / numpy.sum(self.accuracy)
            #log('[Testing] attacked mode accuracy: %g' % debug_accuracy)
            #log('[Testing] only %g of successful attacks are valid' % debug_attack_fraction)
            #log('[Testing] only %g of correct samples are successfully attacked' % debug_test_fraction)

            N_accuracy = numpy.sum(self.accuracy)
            self.results[n]['raw_success'] = numpy.sum(raw_overall_success) / N_accuracy

            self.results[n]['raw_iteration'] = numpy.average(self.success[raw_overall_success])

            self.results[n]['raw_average'] = numpy.average(delta[raw_overall_success]) if numpy.any(raw_overall_success) else 0

            self.results[n]['raw_image'] = numpy.average(image_delta[raw_overall_success]) if numpy.any(raw_overall_success) else 0

            raw_class_success = numpy.zeros((self.N_class, self.perturbation_codes.shape[0]), bool)
            self.results[n]['raw_class_success'] = numpy.zeros((self.N_class))
            self.results[n]['raw_class_average'] = numpy.zeros((self.N_class))
            self.results[n]['raw_class_image'] = numpy.zeros((self.N_class))

            for c in range(self.N_class):
                N_samples = numpy.sum(self.accuracy[self.perturbation_codes[:, 2] == c].astype(int))
                if N_samples <= 0:
                    continue;

                raw_class_success[c] = numpy.logical_and(raw_overall_success, self.perturbation_codes[:, 2] == c)

                self.results[n]['raw_class_success'][c] = numpy.sum(raw_class_success[c]) / N_samples
                if numpy.any(raw_class_success[c]):
                    self.results[n]['raw_class_average'][c] = numpy.average(delta[raw_class_success[c].astype(bool)])
                if numpy.any(raw_class_success[c]):
                    self.results[n]['raw_class_image'][c] = numpy.average(image_delta[raw_class_success[c].astype(bool)])

        if self.args.results_file:
            utils.write_pickle(self.args.results_file, self.results)
            log('[Testing] wrote %s' % self.args.results_file)

    def plot_statistics(self):
        """
        Plot statistics.
        """

        pass

    def plot_manifolds(self):
        """
        Plot manifolds.
        """

        #
        # Plot all classes and adversarial examples in latent space.
        #

        fit = self.test_codes.shape[0]//25
        plot_theta = numpy.concatenate((self.test_theta, self.test_codes[:, 2:3]), axis=1)
        plot_perturbations = numpy.concatenate((self.perturbations, self.perturbation_codes[:, 2:3]), axis=1)
        manifold_visualization = plot.ManifoldVisualization('tsne', pre_pca=None)
        manifold_visualization.fit(plot_theta[:fit])
        log('[Testing] computed t-SNE on test codes')

        for c in range(self.N_class):
            labels = ['Class %d' % (cc + 1) for cc in range(self.N_class)] + ['Adversarial Examples Class %d' % (c + 1)]
            data = numpy.concatenate((
                plot_theta[:fit],
                plot_perturbations[self.perturbation_codes[:, 2] == c]
            ))
            classes = numpy.concatenate((
                self.test_codes[:fit, 2],
                numpy.ones((self.perturbations[self.perturbation_codes[:, 2] == c].shape[0])) * 10,
            ))
            plot_file = os.path.join(self.args.plot_directory, 'latent_perturbations_%d' % (c + 1))
            manifold_visualization.visualize(plot_file, data, classes, labels, title='Adversarial Examples Class %d\n(The adversarial examples are projected into the embedding using learned SVRs)' % c)
            log('[Testing] wrote %s' % plot_file)

        labels = ['Class %d' % (c + 1) for c in range(self.N_class)] + ['Adversarial Examples Class %d' % (c + 1) for c in range(self.N_class)]
        data = numpy.concatenate((
            plot_theta[:fit],
            plot_perturbations
        ))
        classes = numpy.concatenate((
            self.test_codes[:fit, 2],
            self.perturbation_codes[:, 2] + 10,
        ))
        plot_file = os.path.join(self.args.plot_directory, 'latent_perturbations')
        manifold_visualization.visualize(plot_file, data, classes, labels, title='Adversarial Examples\n(The adversarial examples are projected into the embedding using learned SVRs)')
        log('[Testing] wrote %s' % plot_file)

        #
        # Plot all classes and adversarial examples in image space for individual classes as well as all classes.
        #

        test_images = self.test_images.reshape((self.test_images.shape[0], -1))
        manifold_visualization = plot.ManifoldVisualization('tsne', pre_pca=40)
        manifold_visualization.fit(test_images[:fit])
        log('[Testing] computed t-SNE on test images')

        for n in range(self.N_class):
            labels = ['Class %d' % (nn + 1) for nn in range(self.N_class)] + ['Adversarial Examples Class %d' % (n + 1)]
            data = numpy.concatenate((
                test_images[:fit],
                self.perturbation_images[self.perturbation_codes[:, 2] == n]
            ))
            classes = numpy.concatenate((
                self.test_codes[:fit, 2],
                numpy.ones((self.perturbation_images[self.perturbation_codes[:, 2] == n].shape[0])) * 10,
            ))
            plot_file = os.path.join(self.args.plot_directory, 'perturbations_%d' % (n + 1))
            manifold_visualization.visualize(plot_file, data, classes, labels, title='Adversarial Examples Class %d\n(The adversarial examples are projected into the embedding using learned SVRs)' % n)
            log('[Testing] wrote %s' % plot_file)

        labels = ['Class %d' % (n + 1) for n in range(self.N_class)] + ['Adversarial Examples Class %d' % (n + 1) for n in range(self.N_class)]
        data = numpy.concatenate((
            test_images[:fit],
            self.perturbation_images
        ))
        classes = numpy.concatenate((
            self.test_codes[:fit, 2],
            self.perturbation_codes[:, 2] + 10,
        ))
        plot_file = os.path.join(self.args.plot_directory, 'perturbations')
        manifold_visualization.visualize(plot_file, data, classes, labels, title='Adversarial Examples\n(The adversarial examples are projected into the embedding using learned SVRs)')
        log('[Testing] wrote %s' % plot_file)

    def print_statistics(self):
        """
        Print statistics.
        """

        table_data = []
        for n in range(len(self.norms)):
            table_headings = ['(Class) Norm', 'Metric, Epsilon', 'Raw']
            table_data.append(table_headings)
            norm = self.norms[n]

            table_row = ['    L_%.3g' % norm, 'Success Rate', '%.3g' % self.results[n]['raw_success']]
            table_data.append(table_row)

            table_row = ['    L_%.3g' % norm, 'Image Distance', '%.3g' % self.results[n]['raw_average']]
            table_data.append(table_row)

            table_row = ['    L_%.3g' % norm, 'Latent Distance', '%.3g' % self.results[n]['raw_image']]
            table_data.append(table_row)

            for c in range(self.N_class):
                table_row = ['(%d) L_%.3g' % (c, norm), 'Success Rate', '%.3g' % self.results[n]['raw_class_success'][c]]
                table_data.append(table_row)

                table_row = ['(%d) L_%.3g' % (c, norm), 'Image Distance', '%.3g' % self.results[n]['raw_class_average'][c]]
                table_data.append(table_row)

                table_row = ['(%d) L_%.3g' % (c, norm), 'Latent Distance', '%.3g' % self.results[n]['raw_class_image'][c]]
                table_data.append(table_row)
            table_data.append(['---']*(2))

        table = terminaltables.AsciiTable(table_data)
        log(table.table)

    def main(self):
        """
        Main.
        """

        self.load_data()
        self.compute_images()
        self.compute_statistics()
        self.print_statistics()
        if self.args.plot_directory and utils.display():
            self.plot_statistics()
            if self.args.plot_manifolds:
                self.plot_manifolds()


if __name__ == '__main__':
    program = TestAttackDecoderClassifier()
    program.main()
