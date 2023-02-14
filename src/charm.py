#!/usr/bin/env python3
# Copyright 2023 Canonical Limited
# See LICENSE file for licensing details.

"""Charmed Kubernetes Operator for Apache Spark History Server."""


from ops.charm import CharmBase, InstallEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus

from config import SparkHistoryServerConfig
from constants import (
    CONFIG_KEY_S3_LOGS_DIR,
    CONTAINER,
    CONTAINER_LAYER,
    SPARK_HISTORY_SERVER_LAUNCH_CMD,
    SPARK_PROPERTIES_FILE,
    SPARK_USER,
    SPARK_USER_GID,
    SPARK_USER_GROUP,
    SPARK_USER_UID,
    SPARK_USER_WORKDIR,
)
from utils import WithLogging


class SparkHistoryServerCharm(CharmBase, WithLogging):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(
            self.on.spark_history_server_pebble_ready, self._on_spark_history_server_pebble_ready
        )
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.install, self._on_install)
        self.spark_config = SparkHistoryServerConfig(self.model.config)

    def _on_spark_history_server_pebble_ready(self, event):
        """Define and start a workload using the Pebble API."""
        # Get a reference the container attribute on the PebbleReadyEvent
        container = event.workload
        container.push(SPARK_PROPERTIES_FILE, self.spark_config.contents, make_dirs=True)
        # Add initial Pebble config layer using the Pebble API
        container.add_layer(CONTAINER, self._spark_history_server_layer, combine=True)
        # Make Pebble reevaluate its plan, ensuring any services are started if enabled.
        container.replan()
        self.unit.status = BlockedStatus("Pebble ready, waiting for Spark Configuration")

    def _on_config_changed(self, event):
        """Handle changed configuration."""
        # The config is good, so update the configuration of the workload
        container = self.unit.get_container(CONTAINER)
        # Verify that we can connect to the Pebble API in the workload container
        if container.can_connect():
            container.push(
                SPARK_PROPERTIES_FILE,
                self.spark_config.contents,
                user_id=SPARK_USER_UID,
                group_id=SPARK_USER_GID,
                make_dirs=True,
            )

            if not container.exists(SPARK_PROPERTIES_FILE):
                self.logger.error(f"{SPARK_PROPERTIES_FILE} not found")
                self.unit.status = BlockedStatus("Missing service configuration")
                return

            # Push an updated layer with the new config
            container.add_layer(CONTAINER_LAYER, self._spark_history_server_layer, combine=True)
            container.replan()

            self.logger.debug(
                "Spark configuration changed to '%s'",
                self.spark_config.config[CONFIG_KEY_S3_LOGS_DIR],
            )
            self.unit.status = ActiveStatus(
                f"Spark log directory: {self.spark_config.config[CONFIG_KEY_S3_LOGS_DIR]}"
            )
        else:
            # We were unable to connect to the Pebble API, so we defer this event
            event.defer()
            self.unit.status = WaitingStatus("Waiting for Pebble API")

    @property
    def _spark_history_server_layer(self):
        """Return a dictionary representing a Pebble layer."""
        return {
            "summary": "spark history server layer",
            "description": "pebble config layer for spark history server",
            "services": {
                CONTAINER: {
                    "override": "replace",
                    "summary": "spark history server",
                    "command": SPARK_HISTORY_SERVER_LAUNCH_CMD,
                    "user": SPARK_USER,
                    "group": SPARK_USER_GROUP,
                    "working_dir": SPARK_USER_WORKDIR,
                    "startup": "enabled",
                    "environment": {"SPARK_NO_DAEMONIZE": "true"},
                }
            },
        }

    def _on_install(self, event: InstallEvent) -> None:
        """Handle the `on_install` event."""
        self.unit.status = WaitingStatus("Waiting for Pebble")


if __name__ == "__main__":  # pragma: nocover
    main(SparkHistoryServerCharm)
