from __future__ import annotations

import re
from pathlib import Path
from tempfile import TemporaryDirectory

import huggingface_hub
import numpy as np
import skops.io
from sklearn.pipeline import Pipeline

from model2vec.model import PathLike, StaticModel

_DEFAULT_TRUST_PATTERN = re.compile("sklearn\..+")
_DEFAULT_MODEL_FILENAME = "pipeline.skops"


class StaticModelPipeline:
    def __init__(self, model: StaticModel, head: Pipeline) -> None:
        """Create a pipeline with a StaticModel encoder."""
        self.model = model
        self.head = head

    @classmethod
    def from_pretrained(
        cls: type[StaticModelPipeline], path: PathLike, token: str | None = None
    ) -> StaticModelPipeline:
        """
        Load the pipeline from the trained model.

        :param path: The path to the folder containing the pipeline.
        :param token: The token to use to download the pipeline from the hub.
        :return: The loaded pipeline.
        """
        model, head = _load_pipeline(path, token)

        return cls(model, head)

    def save_pretrained(self, path: str) -> None:
        """Save the model to a folder."""
        save_pipeline(self, path)

    def push_to_hub(self, repo_id: str, token: str, private: bool = False) -> None:
        """
        Save a model to a folder, and then push that folder to the hf hub.

        :param repo_id: The id of the repository to push to.
        :param token: The token to use to push to the hub.
        :param private: Whether the repository should be private.
        """
        from model2vec.hf_utils import push_folder_to_hub

        with TemporaryDirectory() as temp_dir:
            save_pipeline(self, temp_dir)
            self.model.save_pretrained(temp_dir)
            push_folder_to_hub(Path(temp_dir), repo_id, private, token)

    def _predict_and_coerce_to_2d(self, X: list[str] | str) -> np.ndarray:
        """Predict the labels of the input and coerce the output to a matrix."""
        encoded = self.model.encode(X)
        if np.ndim(encoded) == 1:
            encoded = encoded[None, :]

        return encoded

    def predict(self, X: list[str] | str) -> list[str]:
        """Predict the labels of the input."""
        encoded = self._predict_and_coerce_to_2d(X)

        return self.head.predict(encoded)

    def predict_proba(self, X: list[str] | str) -> np.ndarray:
        """Predict the probabilities of the labels of the input."""
        encoded = self._predict_and_coerce_to_2d(X)

        return self.head.predict_proba(encoded)


def _load_pipeline(
    folder_or_repo_path: PathLike, token: str | None = None, trust_remote_code: bool = False
) -> Pipeline:
    """
    Load the pipeline from the trained model.

    This assumes the following files are present in the repo:
    - `pipeline.skops`: The head of the pipeline.
    - `config.json`: The configuration of the model.
    - `model.safetensors`: The weights of the model.
    - `tokenizer.json`: The tokenizer of the model.

    :param folder_or_repo_path: The path to the folder containing the pipeline.
    :param token: The token to use to download the pipeline from the hub. If this is None, you will only
        be able to load the pipeline from a local folder, public repository, or a repository that you have access to
        because you are logged in.
    :param trust_remote_code: Whether to trust the remote code. If this is False,
        we will only load components coming from `sklearn`. If this is True, we will load all components.
        If you set this to True, you are responsible for whatever happens.
    :return: The loaded pipeline.
    :raises FileNotFoundError: If the pipeline file does not exist in the folder.
    :raises ValueError: If an untrusted type is found in the pipeline, and `trust_remote_code` is False.
    """
    folder_or_repo_path = Path(folder_or_repo_path)
    model_filename = _DEFAULT_MODEL_FILENAME
    if folder_or_repo_path.exists():
        head_pipeline_path = folder_or_repo_path / model_filename
        if not head_pipeline_path.exists():
            raise FileNotFoundError(f"Pipeline file does not exist in {folder_or_repo_path}")
    else:
        head_pipeline_path = huggingface_hub.hf_hub_download(
            folder_or_repo_path.as_posix(), model_filename, token=token
        )

    model = StaticModel.from_pretrained(folder_or_repo_path)

    unknown_types = skops.io.get_untrusted_types(file=head_pipeline_path)
    # If the user does not trust remote code, we should check that the unknown types are trusted.
    # By default, we trust everything coming from scikit-learn.
    if not trust_remote_code:
        for t in unknown_types:
            if not _DEFAULT_TRUST_PATTERN.match(t):
                raise ValueError(f"Untrusted type {t}.")
    head = skops.io.load(head_pipeline_path, trusted=unknown_types)

    return model, head


def save_pipeline(pipeline: StaticModelPipeline, folder_path: str | Path) -> None:
    """
    Save a pipeline to a folder.

    :param pipeline: The pipeline to save.
    :param folder_path: The path to the folder to save the pipeline to.
    """
    folder_path = Path(folder_path)
    folder_path.mkdir(parents=True, exist_ok=True)
    model_filename = _DEFAULT_MODEL_FILENAME
    head_pipeline_path = folder_path / model_filename
    skops.io.dump(pipeline.head, head_pipeline_path)
    pipeline.model.save_pretrained(folder_path)
