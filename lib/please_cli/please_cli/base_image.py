# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import absolute_import

import json
import os
import subprocess

import click
import click_spinner

import cli_common.log
import cli_common.command
import please_cli.config
import please_cli.utils


log = cli_common.log.get_logger(__name__)


DOCKERFILE = '''
#
# Generated from './please tools build-base-image' command
#

FROM debian:jessie-slim

MAINTAINER rgarbas@mozilla.com


#
# install some package which are needed
#
RUN apt-get -q update \\
 && apt-get -q --yes install bash wget bzip2 tar locales \\
 && apt-get clean \\
 && echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen \\
 && locale-gen

#
# create app user
#
RUN groupadd app \\
 && useradd --create-home -g app app \\
 && mkdir -p /app \\
 && chown app:app /app \\
 && mkdir -m 0755 /nix \\
 && chown app:app /nix \\
 && mkdir -p /etc/nix \\
 && echo "binary-caches = https://cache.mozilla-releng.net https://cache.nixos.org" >> /etc/nix/nix.conf \\
 && echo "trusted-users = app" >> /etc/nix/nix.conf \\
 && echo "allowed-users = *" >> /etc/nix/nix.conf \\
 && chown app:app /etc/nix

USER app
WORKDIR /home/app

#
# Downloading nixpkgs
#
ENV \\
 NIX_PATH="nixpkgs=/home/app/nixpkgs"

RUN wget {nixpkgs_url} \\
 && tar zxf {nixpkgs_rev}.tar.gz \\
 && mv {nixpkgs_repo}-{nixpkgs_rev} /home/app/nixpkgs


#
# installing Nix in multiuser mode
#
ONBUILD ENV \\
 NIX_PATH="nixpkgs=/home/app/nixpkgs"

RUN wget -O- http://nixos.org/releases/nix/nix-1.11.9/nix-1.11.9-x86_64-linux.tar.bz2 | bzcat - | tar vxf - \\
 && USER=app bash /home/app/nix-*-x86_64-linux/install \\
 && echo ". /home/app/.nix-profile/etc/profile.d/nix.sh" >> /home/app/.profile \\
 && rm -r /home/app/nix-*-x86_64-linux \\
 && . /home/app/.profile \\
 && nix-env -iA nixpkgs.cacert \\
 && nix-env -u \\
 && nix-collect-garbage -d \\
 && rm -rf /home/app/.cache/nix


#
# Copy project into /app
#
COPY please /app/
COPY VERSION /app/
COPY nix/ /app/nix/
COPY lib/ /app/lib/

WORKDIR /app

#
# install please command
#
ENV \\
 ENV=/home/app/.profile \\
 PATH=/home/app/.nix-profile/bin:/home/app/.nix-profile/sbin:/bin:/sbin:/usr/bin:/usr/sbin \\
 GIT_SSL_CAINFO=/home/app/.nix-profile/etc/ssl/certs/ca-bundle.crt \\
 LANG=en_US.UTF-8 \\
 NIX_SSL_CERT_FILE=/home/app/.nix-profile/etc/ssl/certs/ca-bundle.crt

RUN . /home/app/.profile \\
 && mkdir /app/tmp \\
 && nix-build /app/nix/default.nix -A please-cli -o /app/tmp/result-please-cli
'''


@click.command(
    cls=please_cli.utils.ClickCustomCommand,
    short_help="Build base docker image.",
    epilog="Happy hacking!",
    )
@click.option(
    '--docker',
    required=True,
    default='docker',
    help='Path to docker command (default: docker).',
    )
@click.option(
    '--docker-username',
    required=True,
    help='https://hub.docker.com username',
    )
@click.option(
    '--docker-password',
    required=True,
    help='https://hub.docker.com password',
    )
@click.option(
    '--docker-repo',
    required=True,
    default=please_cli.config.DOCKER_REPO,
    help='Docker repository (default: {}).'.format(please_cli.config.DOCKER_REPO),
    )
@click.option(
    '--docker-tag',
    required=True,
    default=please_cli.config.DOCKER_BASE_TAG,
    help='Tag of base image (default: {}).'.format(please_cli.config.DOCKER_BASE_TAG),
    )
def cmd(docker_username, docker_password, docker, docker_repo, docker_tag):

    docker_file = os.path.join(please_cli.config.ROOT_DIR, 'Dockerfile')
    nixpkgs_json_file = os.path.join(please_cli.config.ROOT_DIR, 'nix', 'nixpkgs.json')

    with open(nixpkgs_json_file) as f:
        nixpkgs = json.load(f)

    if 'rev' not in nixpkgs or \
       'owner' not in nixpkgs or \
       'repo' not in nixpkgs:
        raise click.ClickException('`nix/nixpkgs.json` is not of correct format.')

    nixpkgs_url = 'https://github.com/{owner}/{repo}/archive/{rev}.tar.gz'.format(**nixpkgs)

    try:
        click.echo(' => Creating Dockerfile ... ', nl=False)
        with click_spinner.spinner():
            with open(docker_file, 'w+') as f:
                f.write(DOCKERFILE.format(
                    nixpkgs_url=nixpkgs_url,
                    nixpkgs_rev=nixpkgs['rev'],
                    nixpkgs_repo=nixpkgs['repo'],
                ))
        please_cli.utils.check_result(0, '')

        click.echo(' => Building base docker image ... ', nl=False)
        with click_spinner.spinner():
            result, output, error = cli_common.command.run(
                [
                    docker,
                    'build',
                    '--no-cache',
                    '--pull',
                    '--force-rm',
                    '-t',
                    '{}:{}'.format(docker_repo, docker_tag),
                    please_cli.config.ROOT_DIR,
                ],
                stream=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        please_cli.utils.check_result(result, output)

        click.echo(' => Logging into hub.docker.com ... ', nl=False)
        with click_spinner.spinner():
            result, output, error = cli_common.command.run(
                [
                    docker,
                    'login',
                    '--username', docker_username,
                    '--password', docker_password,
                ],
                stream=True,
                stderr=subprocess.STDOUT,
                log_command=False,
            )
        please_cli.utils.check_result(result, output)

        click.echo(' => Pushing base docker image ... ', nl=False)
        with click_spinner.spinner():
            result, output, error = cli_common.command.run(
                [
                    docker,
                    'push',
                    '{}:{}'.format(docker_repo, docker_tag),
                ],
                stream=True,
                stderr=subprocess.STDOUT,
            )
        please_cli.utils.check_result(result, output)
    finally:
        if os.path.exists(docker_file):
            os.unlink(docker_file)


if __name__ == "__main__":
    cmd()
