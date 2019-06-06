import torch
from .untargeted_batch_normalized_gradient_method import *
import common.torch


class UntargetedBatchLInfNormalizedGradientMethod(UntargetedBatchNormalizedGradientMethod):
    """
    Implementation of untargetetd PGD attack.
    """

    def __init__(self, model, images, classes=None, epsilon=0.5, base_lr=0.01, max_iterations=500):
        """
        Constructor.

        :param model: model to attack
        :type model: torch.nn.Module
        :param images: image(s) to attack
        :type images: torch.autograd.Variable
        :param classes: true classes, if None, they will be deduced to avoid label leaking
        :type classes: torch.autograd.Variable
        :param epsilon: maximum strength of attack
        :type epsilon: float
        :param base_lr: learning rate if more than one iteration
        :type base_lr: float
        :param max_iterations: maximum number of iterations
        :type max_iterations: int
        """

        super(UntargetedBatchLInfNormalizedGradientMethod, self).__init__(model, images, classes, epsilon, base_lr, max_iterations)

    def initialize_random(self):
        """
        Initialize the attack.
        """

        size = self.images.size()
        random = common.numpy.uniform_ball(size[0], numpy.prod(size[1:]), epsilon=self.epsilon, ord=float('inf'))
        self.perturbations = torch.from_numpy(random.reshape(size).astype(numpy.float32))
        if cuda.is_cuda(self.model):
            self.perturbations = self.perturbations.cuda()
        self.perturbations = torch.autograd.Variable(self.perturbations, requires_grad=True)

    def project(self):
        """
        Project the perturbation.
        """

        for j in range(self.max_projections):
            # We assume that the auto encoder projection already takes care of clipping the
            # output to a valid range!
            # Also note that the order of projections is relevant!
            if self.auto_encoder is not None:
                self.perturbations.data = common.torch.project(self.perturbations.data, self.epsilon, float('inf'))
                self.perturbations.data = self.project_auto_encoder(self.perturbations.data)
            else:
                if self.max_bound is not None:
                    self.perturbations.data = torch.min(self.max_bound - self.images.data, self.perturbations.data)
                if self.min_bound is not None:
                    self.perturbations.data = torch.max(self.min_bound - self.images.data, self.perturbations.data)
                self.perturbations.data = common.torch.project(self.perturbations.data, self.epsilon, float('inf'))

    def norm(self):
        """
        Norm.

        :return: norm of current perturbation
        :rtype: float
        """

        return torch.max(torch.abs(self.perturbations.view(self.perturbations.size()[0], -1)), 1)[0]

    def normalize(self):
        """
        Normalize gradients.
        """

        self.gradients.data = torch.sign(self.gradients.data)