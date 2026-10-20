// Denial Navigator POC - one-command deployment with `azd up`.
targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('azd environment name, used to name resources')
param environmentName string

@minLength(1)
@description('Azure region for all resources (pick one with Azure OpenAI quota for the model below)')
param location string

@description('Chat model to deploy')
param openAiModel string = 'gpt-4.1-mini'

@description('Model version')
param openAiModelVersion string = '2025-04-14'

@description('Deployment capacity in thousands of tokens per minute')
param openAiCapacity int = 30

@secure()
@description('Optional Teams Workflows webhook URL for proactive alerts')
param teamsWebhookUrl string = ''

var tags = { 'azd-env-name': environmentName, workload: 'denial-navigator-poc' }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module app 'resources.bicep' = {
  name: 'denial-navigator'
  scope: rg
  params: {
    location: location
    tags: tags
    token: toLower(uniqueString(subscription().id, environmentName, location))
    openAiModel: openAiModel
    openAiModelVersion: openAiModelVersion
    openAiCapacity: openAiCapacity
    teamsWebhookUrl: teamsWebhookUrl
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = app.outputs.registryLoginServer
output AZURE_OPENAI_ENDPOINT string = app.outputs.openAiEndpoint
output AZURE_OPENAI_DEPLOYMENT string = openAiModel
output SERVICE_WEB_URI string = app.outputs.appUrl
