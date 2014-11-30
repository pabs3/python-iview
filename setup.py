from distutils.core import setup
import iview.config
setup(
    name='iview',
    version=iview.config.version,
    packages=['iview'],
    scripts=['iview-cli', 'iview-gtk'],
    data_files=[('/usr/share/applications', ['iview-gtk.desktop'])],
    )
