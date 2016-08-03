from __future__ import (
    absolute_import,
    division,
    print_function,
    unicode_literals,
)

import base64
import os.path
from functools import partial

from pcs import settings
from pcs.lib import external, reports
from pcs.lib.booth import (
    config_exchange,
    config_files,
    config_structure,
    reports as booth_reports,
    resource,
    status,
    sync,
)
from pcs.lib.booth.config_parser import parse, build
from pcs.lib.booth.env import get_config_file_name
from pcs.lib.cib.tools import get_resources
from pcs.lib.errors import LibraryError
from pcs.lib.node import NodeAddresses


def config_setup(env, booth_configuration, overwrite_existing=False):
    """
    create boot configuration
    list site_list contains site adresses of multisite
    list arbitrator_list contains arbitrator adresses of multisite
    """

    config_structure.validate_peers(
        booth_configuration["sites"],
        booth_configuration["arbitrators"]
    )
    config_content = config_exchange.from_exchange_format(booth_configuration)

    env.booth.create_key(config_files.generate_key(), overwrite_existing)
    config_content = config_structure.set_authfile(
        config_content,
        env.booth.key_path
    )
    env.booth.create_config(build(config_content), overwrite_existing)

def config_destroy(env):
    env.booth.command_expect_live_env("destroy")
    env.command_expect_live_corosync_env("destroy")

    name = env.booth.name
    config_file_path = get_config_file_name(name)
    config_is_used = partial(
        booth_reports.booth_config_is_used,
        config_file_path,
    )

    report_list = []

    if(
        env.is_node_in_cluster()
        and
        resource.find_for_config(get_resources(env.get_cib()), config_file_path)
    ):
        report_list.append(config_is_used("in cib"))

    if external.is_systemctl():
        if external.is_service_running(env.cmd_runner(), "booth", name):
            report_list.append(config_is_used("(running in systemd)"))

        if external.is_service_enabled(env.cmd_runner(), "booth", name):
            report_list.append(config_is_used("(enabled in systemd)"))

    if report_list:
        raise LibraryError(*report_list)

    authfile_path = config_structure.get_authfile(
        parse(env.booth.get_config_content())
    )
    if(
        authfile_path
        and
        os.path.dirname(authfile_path) == settings.booth_config_dir
    ):
        env.booth.set_key_path(authfile_path)
        env.booth.remove_key()
    env.booth.remove_config()

def config_show(env):
    """
    return configuration as tuple of sites list and arbitrators list
    """
    return config_exchange.to_exchange_format(
        parse(env.booth.get_config_content())
    )

def config_ticket_add(env, ticket_name):
    """
    add ticket to booth configuration
    """
    booth_configuration = config_structure.add_ticket(
        parse(env.booth.get_config_content()),
        ticket_name
    )
    env.booth.push_config(build(booth_configuration))

def config_ticket_remove(env, ticket_name):
    """
    remove ticket from booth configuration
    """
    booth_configuration = config_structure.remove_ticket(
        parse(env.booth.get_config_content()),
        ticket_name
    )
    env.booth.push_config(build(booth_configuration))

def create_in_cluster(env, name, ip, resource_create):
    #TODO resource_create is provisional hack until resources are not moved to
    #lib
    resources_section = get_resources(env.get_cib())

    booth_config_file_path = get_config_file_name(name)
    resource.validate_no_booth_resource_using_config(
        resources_section,
        booth_config_file_path
    )

    resource.get_creator(resource_create)(
        ip,
        booth_config_file_path,
        create_id = partial(
            resource.create_resource_id,
            resources_section,
            name
        )
    )

def remove_from_cluster(env, name, resource_remove):
    #TODO resource_remove is provisional hack until resources are not moved to
    #lib
    resource.get_remover(resource_remove)(
        env.report_processor,
        get_resources(env.get_cib()),
        get_config_file_name(name),
    )

def ticket_operation(operation, env, name, ticket, site_ip):
    if not site_ip:
        site_ip = resource.find_binded_single_ip(
            get_resources(env.get_cib()),
            get_config_file_name(name)
        )
        if not site_ip:
            raise LibraryError(
                booth_reports.booth_correct_config_not_found_in_cib(operation)
            )

    command_output, return_code = env.cmd_runner().run([
        settings.booth_binary, operation,
        "-s", site_ip,
        ticket
    ])

    if return_code != 0:
        raise LibraryError(
            booth_reports.booth_ticket_operation_failed(
                operation,
                command_output,
                site_ip,
                ticket
            )
        )

ticket_grant = partial(ticket_operation, "grant")
ticket_revoke = partial(ticket_operation, "revoke")

def config_sync(env, name, skip_offline_nodes=False):
    """
    Send specified local booth configuration to all nodes in cluster.

    env -- LibraryEnvironment
    name -- booth instance name
    skip_offline_nodes -- if True offline nodes will be skipped
    """
    config = env.booth.get_config_content()
    authfile_path = config_structure.get_authfile(parse(config))
    authfile_content = config_files.read_authfile(
        env.report_processor, authfile_path
    )

    sync.send_config_to_all_nodes(
        env.node_communicator(),
        env.report_processor,
        env.get_corosync_conf().get_nodes(),
        name,
        config,
        authfile=authfile_path,
        authfile_data=authfile_content,
        skip_offline=skip_offline_nodes
    )


def _get_booth_instance_name(name=None):
    """
    Returns name of booth service instance.

    name -- string name of booth instance
    """
    return "booth{0}".format(
        "" if name is None else "@{0}".format(name)
    )


def enable_booth(env, name=None):
    """
    Enable specified instance of booth service. Currently it is supported only
    systemd systems.

    env -- LibraryEnvironment
    name -- string, name of booth instance
    """
    external.ensure_is_systemd()
    booth_name = _get_booth_instance_name(name)
    try:
        external.enable_service(env.cmd_runner(), "booth", name)
    except external.EnableServiceError as e:
        raise LibraryError(reports.service_enable_error(booth_name, e.message))
    env.report_processor.process(reports.service_enable_success(booth_name))


def disable_booth(env, name=None):
    """
    Disable specified instance of booth service. Currently it is supported only
    systemd systems.

    env -- LibraryEnvironment
    name -- string, name of booth instance
    """
    external.ensure_is_systemd()
    booth_name = _get_booth_instance_name(name)
    try:
        external.disable_service(env.cmd_runner(), "booth", name)
    except external.DisableServiceError as e:
        raise LibraryError(reports.service_disable_error(booth_name, e.message))
    env.report_processor.process(reports.service_disable_success(booth_name))


def start_booth(env, name=None):
    """
    Start specified instance of booth service. Currently it is supported only
    systemd systems. On non systems it can be run like this:
        BOOTH_CONF_FILE=<booth-file-path> /etc/initd/booth-arbitrator

    env -- LibraryEnvironment
    name -- string, name of booth instance
    """
    external.ensure_is_systemd()
    booth_name = _get_booth_instance_name(name)
    try:
        external.start_service(env.cmd_runner(), "booth", name)
    except external.StartServiceError as e:
        raise LibraryError(reports.service_start_error(booth_name, e.message))
    env.report_processor.process(reports.service_start_success(booth_name))


def stop_booth(env, name=None):
    """
    Stop specified instance of booth service. Currently it is supported only
    systemd systems.

    env -- LibraryEnvironment
    name -- string, name of booth instance
    """
    external.ensure_is_systemd()
    booth_name = _get_booth_instance_name(name)
    try:
        external.stop_service(env.cmd_runner(), "booth", name)
    except external.StopServiceError as e:
        raise LibraryError(reports.service_stop_error(booth_name, e.message))
    env.report_processor.process(reports.service_stop_success(booth_name))


def pull_config(env, node_name, name):
    """
    Get config from specified node and save it on local system. It will
    rewrite existing files.

    env -- LibraryEnvironment
    node_name -- string, name of node from which config should be fetched
    name -- string, name of booth instance of which config should be fetched
    """
    env.report_processor.process(
        booth_reports.booth_fetching_config_from_node(node_name, name)
    )
    output = sync.pull_config_from_node(
        env.node_communicator(), NodeAddresses(node_name), name
    )
    try:
        env.booth.create_config(output["config"]["data"], True)
        if (
            output["authfile"]["name"] is not None and
            output["authfile"]["data"]
        ):
            env.booth.set_key_path(os.path.join(
                settings.booth_config_dir, output["authfile"]["name"]
            ))
            env.booth.create_key(
                base64.b64decode(
                    output["authfile"]["data"].encode("utf-8")
                ),
                True
            )
        env.report_processor.process(booth_reports.booth_config_saved(
            node_name, [name]
        ))
    except KeyError:
        raise LibraryError(reports.invalid_response_format(node_name))


def get_status(env, name=None):
    return {
        "status": status.get_daemon_status(env.cmd_runner(), name),
        "ticket": status.get_tickets_status(env.cmd_runner(), name),
        "peers": status.get_peers_status(env.cmd_runner(), name),
    }
