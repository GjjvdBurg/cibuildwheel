from __future__ import print_function
import argparse, os, subprocess, sys, textwrap

import cibuildwheel
import cibuildwheel.linux, cibuildwheel.windows, cibuildwheel.macos
from cibuildwheel.environment import parse_environment, EnvironmentParseError
from cibuildwheel.util import BuildSelector, Unbuffered

def get_option_from_environment(option_name, platform=None, default=None):
    '''
    Returns an option from the environment, optionally scoped by the platform.

    Example:
      get_option_from_environment('CIBW_COLOR', platform='macos')

      This will return the value of CIBW_COLOR_MACOS if it exists, otherwise the value of
      CIBW_COLOR.
    '''
    if platform:
        option = os.environ.get('%s_%s' % (option_name, platform.upper()))
        if option is not None:
            return option

    return os.environ.get(option_name, default)


def main():
    parser = argparse.ArgumentParser(
        description='Build wheels for all the platforms.',
        epilog=('Most options are supplied via environment variables. '
                'See https://github.com/joerick/cibuildwheel#options for info.'))

    parser.add_argument('--platform',
                        choices=['auto', 'linux', 'macos', 'windows'],
                        default=os.environ.get('CIBW_PLATFORM', 'auto'),
                        help=('Platform to build for. For "linux" you need docker running, on Mac '
                              'or Linux. For "macos", you need a Mac machine, and note that this '
                              'script is going to automatically install MacPython on your system, '
                              'so don\'t run on your development machine. For "windows", you need to '
                              'run in Windows, and it will build and test for all versions of '
                              'Python at C:\\PythonXX[-x64]. Default: auto.'))
    parser.add_argument('--output-dir',
                        default=os.environ.get('CIBW_OUTPUT_DIR', 'wheelhouse'),
                        help='Destination folder for the wheels.')
    parser.add_argument('project_dir',
                        default='.',
                        nargs='?',
                        help=('Path to the project that you want wheels for. Default: the current '
                              'directory.'))

    parser.add_argument('--print-build-identifiers',
                        action='store_true',
                        help='Print the build identifiers matched by the current invocation and exit.')

    args = parser.parse_args()

    if args.platform != 'auto':
        platform = args.platform
    else:
        platform = None

        if os.environ.get('TRAVIS_OS_NAME') == 'linux':
            platform = 'linux'
        elif os.environ.get('TRAVIS_OS_NAME') == 'osx':
            platform = 'macos'
        elif 'APPVEYOR' in os.environ:
            platform = 'windows'
        elif 'BITRISE_BUILD_NUMBER' in os.environ:
            platform = 'macos'
        elif os.environ.get('CIRCLECI'):
            if sys.platform.startswith('linux'):
                platform = 'linux'
            elif sys.platform.startswith('darwin'):
                platform = 'macos'
        elif 'AZURE_HTTP_USER_AGENT' in os.environ:
            if os.environ['AGENT_OS'] == 'Linux':
                platform = 'linux'
            elif os.environ['AGENT_OS'] == 'Darwin':
                platform = 'macos'
            elif os.environ['AGENT_OS'] == 'Windows_NT':
                platform = 'windows'

        if platform is None:
            print('cibuildwheel: Unable to detect platform. cibuildwheel should run on your CI server, '
                  'Travis CI, AppVeyor, and CircleCI are supported. You can run on your development '
                  'machine using the --platform argument. Check --help output for more '
                  'information.',
                  file=sys.stderr)
            exit(2)

    output_dir = args.output_dir
    test_command = get_option_from_environment('CIBW_TEST_COMMAND', platform=platform)
    test_requires = get_option_from_environment('CIBW_TEST_REQUIRES', platform=platform, default='').split()
    test_extras = get_option_from_environment('CIBW_TEST_EXTRAS', platform=platform, default='')
    project_dir = args.project_dir
    before_build = get_option_from_environment('CIBW_BEFORE_BUILD', platform=platform)
    build_verbosity = get_option_from_environment('CIBW_BUILD_VERBOSITY', platform=platform, default='')
    build_config, skip_config = os.environ.get('CIBW_BUILD', '*'), os.environ.get('CIBW_SKIP', '')
    environment_config = get_option_from_environment('CIBW_ENVIRONMENT', platform=platform, default='')

    if test_extras:
        test_extras = '[{0}]'.format(test_extras)

    try:
        build_verbosity = min(3, max(-3, int(build_verbosity)))
    except ValueError:
        build_verbosity = 0

    try:
        environment = parse_environment(environment_config)
    except (EnvironmentParseError, ValueError) as e:
        print('cibuildwheel: Malformed environment option "%s"' % environment_config, file=sys.stderr)
        import traceback
        traceback.print_exc(None, sys.stderr)
        exit(2)

    build_selector = BuildSelector(build_config, skip_config)

    # Add CIBUILDWHEEL environment variable
    # This needs to be passed on to the docker container in linux.py
    os.environ['CIBUILDWHEEL'] = '1'

    if not os.path.exists(os.path.join(project_dir, 'setup.py')):
        print('cibuildwheel: Could not find setup.py at root of project', file=sys.stderr)
        exit(2)

    if args.print_build_identifiers:
        print_build_identifiers(platform, build_selector)
        exit(0)

    build_options = dict(
        project_dir=project_dir,
        output_dir=output_dir,
        test_command=test_command,
        test_requires=test_requires,
        test_extras=test_extras,
        before_build=before_build,
        build_verbosity=build_verbosity,
        build_selector=build_selector,
        environment=environment,
    )

    if platform == 'linux':
        manylinux1_x86_64_image = os.environ.get('CIBW_MANYLINUX1_X86_64_IMAGE', None)
        manylinux1_i686_image = os.environ.get('CIBW_MANYLINUX1_I686_IMAGE', None)

        build_options.update(
            manylinux1_images={'x86_64': manylinux1_x86_64_image, 'i686': manylinux1_i686_image},
        )
    elif platform == 'macos':
        pass
    elif platform == 'windows':
        pass

    # Python is buffering by default when running on the CI platforms, giving problems interleaving subprocess call output with unflushed calls to 'print'
    sys.stdout = Unbuffered(sys.stdout)

    print_preamble(platform, build_options)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    if platform == 'linux':
        cibuildwheel.linux.build(**build_options)
    elif platform == 'windows':
        cibuildwheel.windows.build(**build_options)
    elif platform == 'macos':
        cibuildwheel.macos.build(**build_options)
    else:
        raise Exception('Unsupported platform')


def print_preamble(platform, build_options):
    print(textwrap.dedent('''
             _ _       _ _   _       _           _
         ___|_| |_ _ _|_| |_| |_ _ _| |_ ___ ___| |
        |  _| | . | | | | | . | | | |   | -_| -_| |
        |___|_|___|___|_|_|___|_____|_|_|___|___|_|
        '''))

    print('cibuildwheel version %s\n' % cibuildwheel.__version__)


    print('Build options:')
    print('  platform: %r' % platform)
    for option, value in sorted(build_options.items()):
        print('  %s: %r' % (option, value))

    warnings = detect_warnings(platform, build_options)
    if warnings:
        print('\nWarnings:')
        for warning in warnings:
            print('  ' + warning)

    print('\nHere we go!\n')


def print_build_identifiers(platform, build_selector):
    if platform == 'linux':
        python_configurations = cibuildwheel.linux.get_python_configurations(build_selector)
    elif platform == 'windows':
        python_configurations = cibuildwheel.windows.get_python_configurations(build_selector)
    elif platform == 'macos':
        python_configurations = cibuildwheel.macos.get_python_configurations(build_selector)
    else:
        python_configurations = []

    for config in python_configurations:
        print(config.identifier)


def detect_warnings(platform, build_options):
    warnings = []

    # warn about deprecated {python} and {pip}
    for option_name in ['test_command', 'before_build']:
        option_value = build_options.get(option_name)

        if option_value:
            if '{python}' in option_value or '{pip}' in option_value:
                warnings.append(option_name + ": '{python}' and '{pip}' are no longer needed, and will be removed in a future release. Simply use 'python' or 'pip' instead.")

    return warnings


if __name__ == '__main__':
    main()
