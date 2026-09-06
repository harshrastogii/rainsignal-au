"""Estimator definitions shared by training-time export and serving.

MixedNB lives here rather than in a script because joblib stores a reference to the
class, not its code: the exact same import path must exist when the artefact is
loaded back, or unpickling fails.
"""
from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.naive_bayes import BernoulliNB, GaussianNB


class MixedNB(BaseEstimator, ClassifierMixin):
    """Naive Bayes that models each block with the distribution it actually follows.

    Gaussian likelihood for the standardised numeric columns, Bernoulli for the
    one-hot columns. Stage 2 measured why this matters: a plain GaussianNB over all
    116 columns scored F1 0.4711, because fitting a bell curve to 99 binary dummies
    is the wrong model. Splitting the blocks recovered roughly 0.10 F1.

    The class prior is shared between the two blocks, so it is subtracted once to
    avoid counting it twice.
    """

    def __init__(self, n_numeric: int):
        self.n_numeric = n_numeric

    def fit(self, X, y):
        k = self.n_numeric
        self.gauss_ = GaussianNB().fit(X[:, :k], y)
        self.bern_ = BernoulliNB().fit(X[:, k:], y)
        self.classes_ = self.gauss_.classes_
        self.log_prior_ = np.log(np.bincount(y) / len(y))
        return self

    def _joint(self, X):
        k = self.n_numeric
        return (self.gauss_._joint_log_likelihood(X[:, :k])
                + self.bern_._joint_log_likelihood(X[:, k:])
                - self.log_prior_)

    def predict(self, X):
        return self.classes_[np.argmax(self._joint(X), axis=1)]

    def predict_proba(self, X):
        j = self._joint(X)
        j = j - j.max(axis=1, keepdims=True)
        e = np.exp(j)
        return e / e.sum(axis=1, keepdims=True)
