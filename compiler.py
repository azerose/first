""""Compiling of C++."""

import logging
import pathlib
import platform
import shutil
import subprocess
import tempfile
import typing as t

import argunparse

from ..general import \
    temporarily_change_dir, run_tool, \
    Language, CodeReader, Parser, AstGeneralizer, Unparser, Compiler
from .compiler_interface import GppInterface, ClangppInterface

SWIG_INTERFACE_TEMPLATE = '''/* File: {module_name}.i */
/* Generated by transpyle. */
%module {module_name}

%{{
#define SWIG_FILE_WITH_INIT
{include_directives}
%}}

%include "numpy.i"

%init %{{
import_array();
%}}

// %include "std_valarray.i";
%include "std_vector.i";

namespace std {{
    %template(valarray_double) valarray<double>;
    %template(vector_double) vector<double>;
}}

{function_signatures}
'''

SWIG_INTERFACE_TEMPLATE_HPP = '''/* File: {module_name}.i */
/* Generated by transpyle. */
%module {module_name}

%{{
#define SWIG_FILE_WITH_INIT
#include "{include_path}"
%}}

%include "numpy.i"

%init %{{
import_array();
%}}

// %include "std_valarray.i";
%include "std_list.i";
%include "std_vector.i";
// %include "std_array.i";
%include "std_set.i";
%include "std_map.i";

namespace std {{
//    %template(valarray_double) valarray<double>;
//    %template(array_double) array<double>;
    %template(vector_double) vector<double>;
}}

%include "{include_path}"

// below is Python 3 support, however,
// adding it will generate wrong .so file
// for Fedora 25 on ARMv7. So be sure to
// comment them when you compile for
// Fedora 25 on ARMv7.
%begin %{{
#define SWIG_PYTHON_STRICT_BYTE_CHAR
%}}
'''

_HERE = pathlib.Path(__file__).resolve().parent

TRANSPYLE_CPP_RESOURCES_PATH = _HERE.joinpath('..', 'resources', 'cpp').resolve()

assert TRANSPYLE_CPP_RESOURCES_PATH.is_dir(), TRANSPYLE_CPP_RESOURCES_PATH

_LOG = logging.getLogger(__name__)


class SwigCompiler(Compiler):

    # TODO: create SWIG compiler interface similarily to F2PY interface

    """SWIG-based compiler."""

    def __init__(self, language: Language):
        super().__init__()
        self.language = language
        self.argunparser = argunparse.ArgumentUnparser()

    def create_header_file(self, path: pathlib.Path) -> str:
        """Create a header for a given C/C++ source code file."""
        code_reader = CodeReader()
        parser = Parser.find(self.language)()
        ast_generalizer = AstGeneralizer.find(self.language)({'path': path})
        unparser = Unparser.find(self.language)(headers=True)
        code = code_reader.read_file(path)
        cpp_tree = parser.parse(code, path)
        tree = ast_generalizer.generalize(cpp_tree)
        header_code = unparser.unparse(tree)
        _LOG.debug('unparsed raw header file: """%s"""', header_code)
        return header_code

    def _create_swig_interface(self, path: pathlib.Path) -> str:
        """Create a SWIG interface for a given C/C++ source code file."""
        module_name = path.with_suffix('').name
        header_code = self.create_header_file(path)
        include_directives = []
        function_signatures = []
        for line in header_code.splitlines():
            if line.startswith('#include'):
                collection = include_directives
            else:
                collection = function_signatures
            collection.append(line)
        swig_interface = SWIG_INTERFACE_TEMPLATE.format(
            module_name=module_name, include_directives='\n'.join(include_directives),
            function_signatures='\n'.join(function_signatures))
        _LOG.debug('SWIG interface: """%s"""', swig_interface)
        return swig_interface

    def create_swig_interface(self, path: pathlib.Path) -> str:
        """Create a SWIG interface for a given C/C++ header file."""
        module_name = path.with_suffix('').name
        swig_interface = SWIG_INTERFACE_TEMPLATE_HPP.format(
            module_name=module_name, include_path=path)
        _LOG.debug('SWIG interface: """%s"""', swig_interface)
        return swig_interface

    def run_swig(self, interface_path: pathlib.Path, *args) -> subprocess.CompletedProcess:
        """Run SWIG.

        For C extensions:
        swig -python example.i

        If building a C++ extension, add the -c++ option:
        swig -c++ -python example.i
        """
        swig_cmd = ['swig', '-I{}'.format(TRANSPYLE_CPP_RESOURCES_PATH),
                    '-python', *args, str(interface_path)]
        _LOG.info('running SWIG via %s', swig_cmd)
        return run_tool(pathlib.Path(swig_cmd[0]), swig_cmd[1:])


class CppSwigCompiler(SwigCompiler):

    """SWIG-based compiler for C++."""

    def __init__(self):
        super().__init__(Language.find('C++'))
        self.cpp_compiler = {'Linux': GppInterface(),
                             'Darwin': ClangppInterface()}[platform.system()]

    def compile(self, code: str, path: t.Optional[pathlib.Path] = None,
                output_folder: t.Optional[pathlib.Path] = None, **kwargs) -> pathlib.Path:
        if output_folder is None:
            with tempfile.TemporaryDirectory() as tmpdir:
                output_folder = pathlib.Path(tmpdir)
            output_folder.mkdir()
        header_code = self.create_header_file(path)
        hpp_path = output_folder.joinpath(path.name).with_suffix('.hpp')
        with hpp_path.open('w') as header_file:
            header_file.write(header_code)
        swig_interface = self.create_swig_interface(hpp_path.relative_to(output_folder))
        cpp_path = output_folder.joinpath(path.name)
        shutil.copy2(str(path), str(cpp_path))
        swig_interface_path = output_folder.joinpath(path.with_suffix('.i').name)
        with swig_interface_path.open('w') as swig_interface_file:
            swig_interface_file.write(swig_interface)
        wrapper_path = output_folder.joinpath(path.with_suffix('').name + '_wrap.cxx')

        with temporarily_change_dir(output_folder):
            try:
                self.run_swig(swig_interface_path, '-c++')
            except RuntimeError as err:
                raise RuntimeError('Failed to create SWIG interface for "{}":\n'
                                   'The header "{}" is:\n"""{}"""\nExamine folder "{}" for details'
                                   .format(path, hpp_path, header_code, output_folder)) from err
            result = self.cpp_compiler.compile(
                None, input_paths=[cpp_path, wrapper_path],
                output_path=cpp_path.with_name('_' + cpp_path.name).with_suffix('.so'))
            assert result['results']['compile'].returncode == 0
            assert result['results']['link'].returncode == 0

        return cpp_path.with_suffix('.py')