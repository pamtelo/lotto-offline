"""p4a 기본 numpy 레시피를 병렬(-j) 없이 빌드하도록 바꾼 로컬 레시피.

numpy 1.22 의 lapack_lite 와 umath_linalg 는 같은 f2c 소스를 공유해서, `build_ext -j N` 이면
한쪽이 아직 쓰고 있는 .o 를 다른 쪽이 링크해 'file format not recognized' 로 간헐적으로 실패한다.
"""

import importlib.util
import os

import pythonforandroid

_ORIG_DIR = os.path.join(os.path.dirname(pythonforandroid.__file__), "recipes", "numpy")
_spec = importlib.util.spec_from_file_location(
    "_p4a_numpy_original", os.path.join(_ORIG_DIR, "__init__.py")
)
_orig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_orig)


class SerialNumpyRecipe(_orig.NumpyRecipe):
    # 패치 경로는 레시피 폴더 기준이라, 원래 레시피 폴더의 패치를 절대 경로로 가리킨다
    patches = [os.path.join(_ORIG_DIR, p) for p in _orig.NumpyRecipe.patches]

    def build_compiled_components(self, arch):
        self.setup_extra_args = []
        self._build_compiled_components(arch)

    def rebuild_compiled_components(self, arch, env):
        self.setup_extra_args = []
        self._rebuild_compiled_components(arch, env)


recipe = SerialNumpyRecipe()
