param location string
param tags object
param token string
param openAiModel string
param openAiModelVersion string
param openAiCapacity int
@secure()
param teamsWebhookUrl string

var acrPullRole = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var openAiUserRole = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-dn-${token}'
  location: location
  tags: tags
}

resource logs 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: 'log-dn-${token}'
  location: location
  tags: tags
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'crdn${token}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, acrPullRole)
  scope: registry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRole)
  }
}

// Keyless: local (API key) auth is disabled, the app authenticates with its managed identity.
resource openAi 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: 'oai-dn-${token}'
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: 'oai-dn-${token}'
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource chatModel 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openAi
  name: openAiModel
  sku: { name: 'GlobalStandard', capacity: openAiCapacity }
  properties: {
    model: { format: 'OpenAI', name: openAiModel, version: openAiModelVersion }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
  }
}

resource openAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openAi.id, identity.id, openAiUserRole)
  scope: openAi
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRole)
  }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-dn-${token}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-dn-${token}'
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  dependsOn: [ acrPull ]
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: 8000, transport: 'auto' }
      registries: [ { server: registry.properties.loginServer, identity: identity.id } ]
      secrets: empty(teamsWebhookUrl) ? [] : [ { name: 'teams-webhook', value: teamsWebhookUrl } ]
    }
    template: {
      containers: [
        {
          name: 'web'
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: concat([
            { name: 'AZURE_OPENAI_ENDPOINT', value: openAi.properties.endpoint }
            { name: 'AZURE_OPENAI_DEPLOYMENT', value: chatModel.name }
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'DB_PATH', value: '/tmp/denialnav.db' }
            { name: 'APP_URL', value: 'https://ca-dn-${token}.${env.properties.defaultDomain}' }
          ], empty(teamsWebhookUrl) ? [] : [ { name: 'TEAMS_WEBHOOK_URL', secretRef: 'teams-webhook' } ])
        }
      ]
      // single replica: the POC keeps its working state in a local SQLite file
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

output registryLoginServer string = registry.properties.loginServer
output openAiEndpoint string = openAi.properties.endpoint
output appUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
