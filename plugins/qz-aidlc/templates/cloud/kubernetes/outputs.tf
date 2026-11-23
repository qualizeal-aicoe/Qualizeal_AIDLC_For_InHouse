output "namespace" {
  description = "Where the app runs."
  value       = kubernetes_namespace_v1.app.metadata[0].name
}

output "address" {
  description = "The app's address inside the cluster (a service); empty for a job."
  value       = local.service ? "http://${local.s.slug}.${local.ns}.svc.cluster.local:${local.s.port}" : ""
}

output "keys_to_set" {
  description = "The key names a person puts in the cloud's secret store before the app starts. Nothing here holds a value."
  value       = sort(distinct(concat(values(local.agent_keys), values(local.gateway_keys), local.sie ? ["${local.prefix}-sie-token"] : [])))
}

output "sie_gateway" {
  description = "SIE's OpenAI-compatible endpoint inside the cluster, which the gateway calls with SIE's token."
  value       = local.sie ? local.gateway_env.SIE_API_BASE : ""
}
