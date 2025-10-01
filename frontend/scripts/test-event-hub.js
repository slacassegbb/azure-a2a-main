/**
 * Event Hub Connection Test Script
 * 
 * This script tests the Azure Event Hub connection with your current configuration.
 * Run this to verify that your Event Hub settings are working correctly.
 */

const { EventHubConsumerClient } = require("@azure/event-hubs");
const { DefaultAzureCredential } = require("@azure/identity");

async function testEventHubConnection() {
  console.log("[Test] Starting Event Hub connection test...");

  // Load environment variables (same as in your .env)
  const connectionString = process.env.NEXT_PUBLIC_AZURE_EVENTHUB_CONNECTION_STRING;
  const eventHubName = process.env.NEXT_PUBLIC_AZURE_EVENTHUB_NAME;
  const consumerGroup = process.env.NEXT_PUBLIC_AZURE_EVENTHUB_CONSUMER_GROUP || "$Default";

  console.log("[Test] Configuration:");
  console.log("- Event Hub Name:", eventHubName);
  console.log("- Consumer Group:", consumerGroup);
  console.log("- Has Connection String:", !!connectionString);

  if (!eventHubName) {
    console.error("[Test] ❌ NEXT_PUBLIC_AZURE_EVENTHUB_NAME is not configured");
    return false;
  }

  if (!connectionString) {
    console.error("[Test] ❌ NEXT_PUBLIC_AZURE_EVENTHUB_CONNECTION_STRING is not configured");
    return false;
  }

  try {
    console.log("[Test] Creating Event Hub consumer client...");
    
    const consumerClient = new EventHubConsumerClient(
      consumerGroup,
      connectionString,
      eventHubName
    );

    console.log("[Test] ✅ Consumer client created successfully");

    // Test the connection by getting Event Hub properties
    console.log("[Test] Getting Event Hub properties...");
    const properties = await consumerClient.getEventHubProperties();
    
    console.log("[Test] ✅ Event Hub properties retrieved:");
    console.log("- Event Hub Name:", properties.name);
    console.log("- Created At:", properties.createdOn);
    console.log("- Partition IDs:", properties.partitionIds);

    // Test getting partition information
    console.log("[Test] Getting partition information...");
    for (const partitionId of properties.partitionIds) {
      const partitionInfo = await consumerClient.getPartitionProperties(partitionId);
      console.log(`- Partition ${partitionId}: Last sequence number: ${partitionInfo.lastEnqueuedSequenceNumber}`);
    }

    // Close the client
    await consumerClient.close();
    console.log("[Test] ✅ Connection test completed successfully!");
    return true;

  } catch (error) {
    console.error("[Test] ❌ Connection test failed:");
    console.error("Error:", error);

    if (error instanceof Error) {
      if (error.message.includes("Unauthorized")) {
        console.error("\n🔧 Possible fixes:");
        console.error("1. Check if the connection string is correct");
        console.error("2. Verify the SharedAccessKey has the required permissions");
        console.error("3. Ensure the Event Hub name is correct");
      } else if (error.message.includes("not found")) {
        console.error("\n🔧 Possible fixes:");
        console.error("1. Verify the Event Hub namespace exists");
        console.error("2. Check if the Event Hub name is correct");
        console.error("3. Ensure the connection string points to the right namespace");
      }
    }

    return false;
  }
}

// If running as a script
if (require.main === module) {
  // Load environment variables from .env file
  require('dotenv').config({ path: '.env' });
  
  testEventHubConnection()
    .then((success) => {
      process.exit(success ? 0 : 1);
    })
    .catch((error) => {
      console.error("Unexpected error:", error);
      process.exit(1);
    });
}

module.exports = { testEventHubConnection };
