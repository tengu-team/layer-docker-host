#!/usr/bin/env python3
from time import sleep
from subprocess import check_call

from charmhelpers.contrib.python.packages import pip_install

import docker
from charmhelpers.core import host
from charmhelpers.core.hookenv import (
    status_set,
    open_port,
    close_port,
    log,
    unit_private_ip,
)

from charms.reactive import set_state, remove_state, when, when_not

@when('docker.ready')
@when_not('docker-host.pip')
def install_docker_pip():
    pip_install('docker')
    set_state('docker-host.pip')


@when('docker-image-host.available', 'docker.available', 'docker-host.pip')
def run_images(relation):
    container_requests = relation.container_requests
    running_containers = {}
    log(container_requests)
    for container_request in container_requests:
        service, unit = container_request['unit'].split('/', 1)
        running_containers[container_request['unit']] = ensure_running(service, unit, container_request)
    relation.send_running_containers(running_containers)


@when('docker-image-host.broken', 'docker-host.pip')
def remove_images(relation):
    container_requests = relation.container_requests
    log(container_requests)
    for container_request in container_requests:
        service, unit = container_request['unit'].split('/', 1)
        remove(service, unit)
    remove_state('docker-image-host.broken')


def ensure_running(service, unit, container_request):
    '''When the provided image is not running, set it up and run it. '''
    client = docker.from_env(version="auto")
    image = container_request['image']
    kwargs = {
        'labels': {},
        'detach': True,
        'publish_all_ports': True,
    }
    kwargs['labels'][service] = unit
    image_obj = client.images.pull(image)
    # Only start container when it is not already running
    containers = client.containers.list(filters={'label': '{}={}'.format(service, unit)})
    if len(containers) > 0:
        #container with specified label already exists
        log("The container with label={}={} already exists.".format(service, unit))
        container = containers[0]
        if container.image.attrs['RepoTags'] == image_obj.attrs['RepoTags']:
            log("The running container also has the same image {}, so do nothing.".format(image_obj.attrs['RepoTags'][0]))
        else:
            log("The running container has a different image {} (required: {}),"
                " so removing this container and starting a new container.".format(container.image.attrs['RepoTags'][0], image_obj.attrs['RepoTags'][0]))
            remove(service, unit)
            log("Starting docker container. This might take a while.\n"
                "\tImage: {}\n\tkwargs: {}".format(image, kwargs))
            container = client.containers.run(image, None, **kwargs)
    else:
        log("Starting docker container. This might take a while.\n"
            "\tImage: {}\n\tkwargs: {}".format(image, kwargs))
        container = client.containers.run(image, None, **kwargs)
        #while container.status != "running":
        #    sleep(1)
        #    # Refresh the python object to show the latest info
        #    container.reload()
    
    # Expose ports
    ports = container.attrs['NetworkSettings']['Ports'] or {}
    open_ports = {}
    for exposed_port in ports.keys():
        log("exp_port: " + exposed_port)
        proto = exposed_port.split('/')[1]
        for host_portip in ports[exposed_port]:
            log("host_portip " + str(host_portip))
            open_port(host_portip['HostPort'], protocol=proto)
            open_ports[exposed_port.split('/')[0]] = host_portip['HostPort']
    return {
        'host': unit_private_ip(),
        'ports': open_ports,
    }


def remove(service, unit):
    client = docker.from_env(version="auto")
    containers = client.containers.list(filters={'label': '{}={}'.format(service, unit)})
    if len(containers) > 0:
        for container in containers:
            #container with specified label exists
            log("The container with label={}={} exists.".format(service, unit))
            container.remove(force=True)
            
            # Unexpose ports
            ports = container.attrs['NetworkSettings']['Ports'] or {}
            for exposed_port in ports.keys():
                log("exp_port: " + exposed_port)
                proto = exposed_port.split('/')[1]
                for host_portip in ports[exposed_port]:
                    log("host_portip " + str(host_portip))
                    close_port(host_portip['HostPort'], protocol=proto)
    else:
        log("No containers with label={}={} found, so nothing to remove.".format(service, unit))


