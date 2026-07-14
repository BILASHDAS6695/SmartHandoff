terraform {
  backend "gcs" {
    bucket  = "smarthandoff-tf-state-prod"
    prefix  = "terraform/state"
  }
}
