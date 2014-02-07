from setuptools import setup, find_packages

version = '0.1'

setup(name="helga-codereview",
      version=version,
      description=('Reviewboard code reviews'),
      classifiers=['Development Status :: 4 - Beta',
                   'Environment :: IRC',
                   'License :: OSI Approved :: MIT License',
                   'Operating System :: OS Independent',
                   'Programming Language :: Python',
                   'Topic :: Software Development :: Libraries :: Python Modules',
                   'Topic :: IRC Bots'],
      keywords='irc helga reviewboard',
      author='Shaun Duncan',
      author_email='shaun.duncan@gmail.com',
      url='https://github.com/shaunduncan/helga-codereview',
      license='MIT',
      install_requires=[
          'RBTools==0.5.7',
          'flake8==2.1.0',
      ],
      packages=find_packages(),
      entry_points = dict(
          helga_plugins=[
              'codereview= helga_codereview:codereview',
          ],
      ),
)
