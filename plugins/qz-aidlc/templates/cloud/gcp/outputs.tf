output "keys_to_set" {
  description = "The Secret Manager secrets a person adds a version to before setting start_app = true. Nothing here holds a value."
  value       = sort([for k in local.key_names : google_secret_manager_secret.keys[k].secret_id])
}

output "service_account" {
  description = "The account the app and its gateway act as."
  value       = google_service_account.app.email
}

output "service" {
  description = "The Cloud Run service (empty for a job, or before start_app)."
  value       = length(google_cloud_run_v2_service.app) > 0 ? google_cloud_run_v2_service.app[0].name : ""
}

output "job" {
  description = "The Cloud Run job (empty for a service)."
  value       = length(google_cloud_run_v2_job.app) > 0 ? google_cloud_run_v2_job.app[0].name : ""
}
