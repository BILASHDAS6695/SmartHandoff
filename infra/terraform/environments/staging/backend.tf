terraform {
  backend "gcs" {
    bucket  = "smarthandoff-tf-state-staging"
    prefix  = "terraform/state"
  }
}
