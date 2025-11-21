import json
import boto3
import os

glue_client = boto3.client('glue')

def lambda_handler(event, context):
    """
    Lambda function to trigger Glue job from EventBridge S3 events
    """
    try:
        # Extract bucket and key from EventBridge event
        bucket_name = event['detail']['bucket']['name']
        object_key = event['detail']['object']['key']
        
        # Get environment variables
        glue_job_name = os.environ.get('GLUE_JOB_NAME', 'KnowledgeBaseProcessor')
        
        print(f"Triggering Glue job: {glue_job_name}")
        print(f"Bucket: {bucket_name}")
        print(f"Triggered by: {object_key}")
        print(f"Mode: Process all unprocessed files")
        
        # Build arguments - only BUCKET_NAME needed
        arguments = {
            '--BUCKET_NAME': bucket_name
        }
        
        # Start Glue job with parameters
        response = glue_client.start_job_run(
            JobName=glue_job_name,
            Arguments=arguments
        )
        
        job_run_id = response['JobRunId']
        
        print(f"Successfully started Glue job. JobRunId: {job_run_id}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Glue job triggered successfully',
                'jobRunId': job_run_id,
                'jobName': glue_job_name
            })
        }
        
    except Exception as e:
        print(f"Error triggering Glue job: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'message': 'Error triggering Glue job',
                'error': str(e)
            })
        }
