output "vpc_id" {
  description = "Self-link ID of the VPC network"
  value       = google_compute_network.vpc.id
}

output "vpc_name" {
  description = "Name of the VPC network"
  value       = google_compute_network.vpc.name
}

output "services_subnet_id" {
  description = "Self-link ID of the services subnet (10.0.1.0/24)"
  value       = google_compute_subnetwork.services.id
}

output "data_subnet_id" {
  description = "Self-link ID of the data subnet (10.0.2.0/24)"
  value       = google_compute_subnetwork.data.id
}

output "vpc_connector_id" {
  description = "ID of the Serverless VPC Access connector"
  value       = google_vpc_access_connector.connector.id
}

output "private_vpc_connection_id" {
  description = "ID of the private services access peering connection (required by Cloud SQL)"
  value       = google_service_networking_connection.private_vpc_connection.id
}
