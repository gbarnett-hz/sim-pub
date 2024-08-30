terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "region_name" {
  type = string
}

variable "table_name" {
  type = string
}

provider "aws" {
  region = var.region_name
}

resource "aws_dynamodb_table" "simulator_table" {
  name           = var.table_name
  billing_mode   = "PROVISIONED"
  read_capacity  = 1
  write_capacity = 1
  hash_key       = "version"
  range_key      = "test_file"

  attribute {
    name = "version"
    type = "S"
  }

  attribute {
    name = "test_file"
    type = "S"
  }

}
