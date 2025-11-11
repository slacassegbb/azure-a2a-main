import os
from typing import Annotated
from pydantic import Field
from contoso_agents.network_performance_agent.dataagents.main import ask_fabric_agent
import logging


logger = logging.getLogger("contoso_agents.network_performance_agent.tools")
_airport_info_endpoint = None
_network_perf_endpoint = None
_azure_credential = None


def set_airport_endpoint(endpoint: str):
    """Set the Fabric endpoint for airport info queries."""
    global _airport_info_endpoint
    _airport_info_endpoint = endpoint
    logger.info(f"🌐 Fabric endpoint configured: {endpoint}")


def set_network_performance_endpoint(endpoint: str):
    """Set the Fabric endpoint for network performance queries."""
    global _network_perf_endpoint
    _network_perf_endpoint = endpoint
    logger.info(f"🌐 Network Performance Fabric endpoint configured: {endpoint}")


def set_azure_credential(credential):
    """Set the cached Azure credential for this module."""
    global _azure_credential
    _azure_credential = credential
    logger.info("🔐 Azure credential cached for network performance tools")


def retrieve_operational_context(
    query: Annotated[
        str,
        Field(
            description="Query about customer network performance, device status, ping history, connectivity metrics, or historical operational data"
        ),
    ]
) -> str:
    """
    Retrieve historical network operational data from Microsoft Fabric.

    This tool queries the Fabric data agent to retrieve accurate historical
    network performance data including:
    - Customer network topology and device inventory
    - Historical ping test results and latency metrics
    - Packet loss statistics over time
    - Device connectivity patterns and status
    - Network reset history and effectiveness
    - Modem and pod performance data
    - Customer-specific network configurations

    :param query: The network operational question or data request (include customer_id when relevant)
    :return: Retrieved network performance data from Fabric
    """
    try:
        logger.info("=" * 80)
        logger.info("🔧 TOOL EXECUTION: retrieve_operational_context")
        logger.info(f"📋 Query: {query}")
        logger.info("=" * 80)

        # Use network performance endpoint if available, fallback to airport_info for testing
        endpoint = _network_perf_endpoint if _network_perf_endpoint else _airport_info_endpoint
        
        if not endpoint:
            error_msg = "No Fabric endpoint configured. Please configure network_performance endpoint."
            logger.error(f"❌ {error_msg}")
            return error_msg

        # Query the Fabric agent with the network performance endpoint
        response = ask_fabric_agent(
            endpoint=endpoint, 
            question=query,
            credential=_azure_credential
        )

        logger.info("✅ Network operational data retrieved successfully from Fabric")
        logger.info("=" * 80)
        return response

    except Exception as e:
        error_msg = f"Error retrieving network operational data: {str(e)}"
        logger.error(f"❌ {error_msg}")
        logger.info("=" * 80)
        return error_msg