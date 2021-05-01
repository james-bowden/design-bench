from design_bench.oracles.approximate_oracle import ApproximateOracle
from design_bench.datasets.discrete_dataset import DiscreteDataset
from design_bench.datasets.dataset_builder import DatasetBuilder
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Kernel, RBF
from sklearn.gaussian_process.kernels import GenericKernelMixin
import numpy as np
import pickle as pkl


class DiscreteSequenceKernel(GenericKernelMixin, Kernel):

    def __init__(self, kernel_matrix):
        self.kernel_matrix = kernel_matrix

    def evaluate_kernel(self, x, y):
        return self.kernel_matrix[x][:, y].sum()

    def __call__(self, X, Y=None, eval_gradient=False):
        return np.array([[self.evaluate_kernel(
            x, y) for y in (X if Y is None else Y)] for x in X])

    def diag(self, X):
        return np.array([self.evaluate_kernel(x, x) for x in X])

    def is_stationary(self):
        return True  # the kernel is fixed in advance


class GaussianProcessOracle(ApproximateOracle):
    """An abstract class for managing the ground truth score functions f(x)
    for model-based optimization problems, where the
    goal is to find a design 'x' that maximizes a prediction 'y':

    max_x { y = f(x) }

    Public Attributes:

    dataset: DatasetBuilder
        an instance of a subclass of the DatasetBuilder class which has
        a set of design values 'x' and prediction values 'y', and defines
        batching and sampling methods for those attributes

    is_batched: bool
        a boolean variable that indicates whether the evaluation function
        implemented for a particular oracle is batched, which effects
        the scaling coefficient of its computational cost

    internal_batch_size: int
        an integer representing the number of design values to process
        internally at the same time, if None defaults to the entire
        tensor given to the self.score method
    internal_measurements: int
        an integer representing the number of independent measurements of
        the prediction made by the oracle, which are subsequently
        averaged, and is useful when the oracle is stochastic

    noise_std: float
        the standard deviation of gaussian noise added to the prediction
        values 'y' coming out of the ground truth score function f(x)
        in order to make the optimization problem difficult

    expect_normalized_y: bool
        a boolean indicator that specifies whether the inputs to the oracle
        score function are expected to be normalized
    expect_normalized_x: bool
        a boolean indicator that specifies whether the outputs of the oracle
        score function are expected to be normalized
    expect_logits: bool
        a boolean that specifies whether the oracle score function is
        expecting logits when the dataset is discrete

    Public Methods:

    score(np.ndarray) -> np.ndarray:
        a function that accepts a batch of design values 'x' as input and for
        each design computes a prediction value 'y' which corresponds
        to the score in a model-based optimization problem

    check_input_format(DatasetBuilder) -> bool:
        a function that accepts a list of integers as input and returns true
        when design values 'x' with the shape specified by that list are
        compatible with this class of approximate oracle

    fit(np.ndarray, np.ndarray):
        a function that accepts a data set of design values 'x' and prediction
        values 'y' and fits an approximate oracle to serve as the ground
        truth function f(x) in a model-based optimization problem

    """

    def __init__(self, dataset: DatasetBuilder, noise_std=0.0, **kwargs):
        """Initialize the ground truth score function f(x) for a model-based
        optimization problem, which involves loading the parameters of an
        oracle model and estimating its computational cost

        Arguments:

        dataset: DatasetBuilder
            an instance of a subclass of the DatasetBuilder class which has
            a set of design values 'x' and prediction values 'y', and defines
            batching and sampling methods for those attributes
        noise_std: float
            the standard deviation of gaussian noise added to the prediction
            values 'y' coming out of the ground truth score function f(x)
            in order to make the optimization problem difficult

        """

        # initialize the oracle using the super class
        super(GaussianProcessOracle, self).__init__(
            dataset, noise_std=noise_std, is_batched=True,
            internal_batch_size=32, internal_measurements=1,
            expect_normalized_y=True,
            expect_normalized_x=not isinstance(dataset, DiscreteDataset),
            expect_logits=False if isinstance(
                dataset, DiscreteDataset) else None, **kwargs)

    def check_input_format(self, dataset):
        """a function that accepts a model-based optimization dataset as input
        and determines whether the provided dataset is compatible with this
        oracle score function (is this oracle a correct one)

        Arguments:

        dataset: DatasetBuilder
            an instance of a subclass of the DatasetBuilder class which has
            a set of design values 'x' and prediction values 'y', and defines
            batching and sampling methods for those attributes

        Returns:

        is_compatible: bool
            a boolean indicator that is true when the specified dataset is
            compatible with this ground truth score function

        """

        return True  # any data set is always supported with this model

    @staticmethod
    def save_model_to_zip(model, zip_archive):
        """a function that serializes a machine learning model and stores
        that model in a compressed zip file using the python ZipFile interface
        for sharing and future loading by an ApproximateOracle

        Arguments:

        model: Any
            any format of of machine learning model that will be stored
            in the self.model attribute for later use

        zip_archive: ZipFile
            an instance of the python ZipFile interface that has loaded
            the file path specified by self.resource.disk_target

        """

        with zip_archive.open('gaussian_process.pkl', "w") as file:
            return pkl.dump(model, file)  # save the model using pickle

    @staticmethod
    def load_model_from_zip(zip_archive):
        """a function that loads components of a serialized model from a zip
        given zip file using the python ZipFile interface and returns an
        instance of the model

        Arguments:

        zip_archive: ZipFile
            an instance of the python ZipFile interface that has loaded
            the file path specified by self.resource.disk_targetteh

        Returns:

        model: Any
            any format of of machine learning model that will be stored
            in the self.model attribute for later use

        """

        with zip_archive.open('gaussian_process.pkl', "r") as file:
            return pkl.load(file)  # load the random forest using pickle

    @staticmethod
    def fit(dataset, kernel=None, max_samples=1000, **kwargs):
        """a function that accepts a set of design values 'x' and prediction
        values 'y' and fits an approximate oracle to serve as the ground
        truth function f(x) in a model-based optimization problem

        Arguments:

        dataset: DatasetBuilder
            an instance of a subclass of the DatasetBuilder class which has
            a set of design values 'x' and prediction values 'y', and defines
            batching and sampling methods for those attributes
        kernel: Kernel or np.ndarray
            an instance of an sklearn Kernel if the dataset is continuous or
            an instance of a numpy array if the dataset is discrete, which
            will be passed to an instance of DiscreteSequenceKernel
        max_samples: int
            the maximum number of samples to be used when fitting a gaussian
            process, where the dataset is uniformly randomly sub sampled
            if the dataset is larger than max_samples

        Returns:

        model: Any
            any format of of machine learning model that will be stored
            in the self.model attribute for later use

        """

        # if the data set is discrete use a discrete kernel
        if isinstance(dataset, DiscreteDataset):
            if kernel is None:
                n = dataset.num_classes
                kernel = 0.9 * np.eye(n) + 0.1 * np.ones((n, n))
            kernel = DiscreteSequenceKernel(kernel)

        # otherwise if no kernel is provided use an RBF kernel
        elif kernel is None:
            kernel = RBF(length_scale=1.0,
                         length_scale_bounds=(1e-5, 1e5))

        # build the model class and assign hyper parameters
        model = GaussianProcessRegressor(kernel=kernel, **kwargs)

        # sample the entire dataset without transformations
        # note this requires the dataset to be loaded in memory all at once
        dataset._disable_transform = True
        x = dataset.x
        y = dataset.y

        # randomly remove samples from the training dataset
        # this is particularly important when the dataset is very large
        indices = np.random.choice(y.shape[0], replace=False,
                                   size=min(y.shape[0], max_samples))
        x = x[indices]
        y = y[indices]

        # convert integers to floating point logits
        # we do this because sklearn cannot support discrete features
        if isinstance(dataset, DiscreteDataset) and \
                np.issubdtype(x.dtype, np.floating):
            x = dataset.to_integers(x)

        if np.issubdtype(x.dtype, np.floating):
            x = dataset.normalize_x(x)

        y = dataset.normalize_y(y)

        # fit the random forest model to the dataset
        model.fit(x.reshape((x.shape[0], np.prod(x.shape[1:]))),
                  y.reshape((y.shape[0],)))

        # cleanup the dataset and return the trained model
        dataset._disable_transform = False
        return model

    def protected_score(self, x):
        """Score function to be implemented by oracle subclasses, where x is
        either a batch of designs if self.is_batched is True or is a
        single design when self._is_batched is False

        Arguments:

        x_batch: np.ndarray
            a batch or single design 'x' that will be given as input to the
            oracle model in order to obtain a prediction value 'y' for
            each 'x' which is then returned

        Returns:

        y_batch: np.ndarray
            a batch or single prediction 'y' made by the oracle model,
            corresponding to the ground truth score for each design
            value 'x' in a model-based optimization problem

        """

        # call the model's predict function to generate predictions
        return self.model.predict(x)[:, np.newaxis]
