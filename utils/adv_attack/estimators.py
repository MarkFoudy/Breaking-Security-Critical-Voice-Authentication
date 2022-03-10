# pylint: disable=W0221, E1102, W0703

from abc import ABC
import numpy as np
import torch

from art.estimators.estimator import BaseEstimator, LossGradientsMixin
from art.estimators.classification.classifier import ClassGradientsMixin
from art.estimators.classification.classifier import ClassifierMixin
import components
from utils.eval import model_loaders


class ESTIMATOR(
    BaseEstimator, ClassGradientsMixin, ClassifierMixin, LossGradientsMixin, ABC
):
    nb_classes = 2
    input_shape = ()

    def __init__(self, device, loader, config, loss=None):
        BaseEstimator.__init__(self, model=None, clip_values=(-1, 1))
        ClassGradientsMixin.__init__(self)
        ClassifierMixin.__init__(self)
        LossGradientsMixin.__init__(self)

        system, eer, logits, args = getattr(model_loaders, loader)(
            config, device, loss=loss
        )
        self.attack = getattr(components, system)(**args)
        self.device = device
        self.eer = np.array(eer)
        self.logits = logits

    def fit(self, x, y, **kwargs) -> None:
        return

    def set_input_shape(self, value):
        setattr(self, "input_shape", value)

    def set_ref(self, x, device):
        try:
            self.attack.set_ref(x, device)

        except Exception:
            pass

    def class_gradient(self, x, label):
        var = torch.tensor(x, device=self.device, dtype=torch.float, requires_grad=True)
        score = self.attack.get_score(var)[:, label[0]]
        score.backward()
        grad = var.grad.detach().cpu().numpy()
        return grad

    def _loss(self, var, y):
        y = torch.tensor(np.argmax(y, axis=1), device=self.device).repeat(var.shape[0])
        loss = self.attack.attack_pipeline(var, y)
        return loss

    def compute_loss(self, x, y, reduction="mean"):
        # pylint: disable=W0613
        var = torch.tensor(x, device=self.device, dtype=torch.float)
        loss = self._loss(var, y).detach().cpu().numpy()
        return loss

    def loss_gradient(self, x, y):
        var = torch.tensor(x, device=self.device, dtype=torch.float, requires_grad=True)
        loss = self._loss(var, y)
        loss.backward(retain_graph=True)
        grad = var.grad.detach().cpu().numpy()

        # grad[ abs(grad) < np.max(np.abs(grad)) * 0.2] = 0
        # grad[ abs(grad) < np.max(np.abs(grad)) * 0.3] = 0

        return grad

    def predict(self, x, logits=None, batch_size=1):
        # pylint: disable=W0613
        var = torch.tensor(x, device=self.device, dtype=torch.float)
        pred = self.attack.get_score(var, self.logits).detach().cpu().numpy()

        # Find a better aggregation method for ADVJOINT (fixme)
        if np.prod(pred.shape) > 2:
            if (np.array([pred[0][1], pred[1][1]]) > self.eer).all():
                return np.array([[0.0, 1.0]])
            return np.array([[1.0, 0.0]])
        return pred

    def result(self, x, label):
        score = (
            self.attack.get_score(
                torch.tensor(x, device=self.device, dtype=torch.float),
                ret_logits=self.logits,
            )[:, 1]
            .squeeze()
            .unsqueeze(0)[0]
            .detach()
            .cpu()
            .numpy()
        )

        result = ((score < self.eer).all() and label == 0) or (
            (score >= self.eer).all() and label == 1
        )

        ret = "FAIL"
        if result == 1:
            ret = "SUCCESS"
        return [(ret, str(score) + "|" + str(self.eer))]
