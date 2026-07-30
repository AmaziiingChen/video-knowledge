const PROXY_ENVIRONMENT_NAMES = [
  'ALL_PROXY',
  'HTTP_PROXY',
  'HTTPS_PROXY',
  'NO_PROXY',
  'all_proxy',
  'http_proxy',
  'https_proxy',
  'no_proxy',
]

function directChildEnvironment(environment = {}) {
  const result = { ...environment }
  for (const name of PROXY_ENVIRONMENT_NAMES) delete result[name]
  return result
}

module.exports = { directChildEnvironment }
