import { Construct } from "constructs";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import { WebSocketLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import { Runtime, SnapStartConf } from "aws-cdk-lib/aws-lambda";
import * as path from "path";
import * as iam from "aws-cdk-lib/aws-iam";
import { CfnOutput, Duration, Stack, StackProps } from "aws-cdk-lib";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import { excludeDockerImage } from "./constants/docker";
import { PythonFunction } from "@aws-cdk/aws-lambda-python-alpha";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as ssm from "aws-cdk-lib/aws-ssm";

interface PublishedWebSocketStackProps extends StackProps {
  readonly bedrockRegion: string;
  readonly conversationTableName: string;
  readonly botTableName: string;
  readonly tableAccessRoleArn: string;
  readonly largeMessageBucketName: string;
  readonly enableBedrockCrossRegionInference: boolean;
  readonly enableLambdaSnapStart: boolean;
  readonly botId: string;
  readonly apiKey: string;
}

export class PublishedWebSocketStack extends Stack {
  readonly webSocketApi: apigwv2.IWebSocketApi;
  private readonly defaultStageName = "prod";

  constructor(scope: Construct, id: string, props: PublishedWebSocketStackProps) {
    super(scope, id, props);

    // Reference existing SSM Parameter (created by deploy script)
    const apiKeyParameter = ssm.StringParameter.fromStringParameterName(
      this,
      "ApiKeyParameter",
      `/bedrock-chat/published-bot/${props.botId}/api-key`
    );

    // Session table for WebSocket connections
    const sessionTable = new dynamodb.Table(this, "SessionTable", {
      partitionKey: {
        name: "ConnectionId",
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: "MessagePartId",
        type: dynamodb.AttributeType.NUMBER,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: "expire",
    });

    const handlerRole = new iam.Role(this, "HandlerRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
    });
    handlerRole.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName(
        "service-role/AWSLambdaBasicExecutionRole"
      )
    );
    handlerRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["sts:AssumeRole"],
        resources: [props.tableAccessRoleArn],
      })
    );
    handlerRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:*"],
        resources: ["*"],
      })
    );
    handlerRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["ssm:GetParameter"],
        resources: [apiKeyParameter.parameterArn],
      })
    );

    const largeMessageBucket = s3.Bucket.fromBucketName(
      this,
      "LargeMessageBucket",
      props.largeMessageBucketName
    );
    largeMessageBucket.grantReadWrite(handlerRole);
    sessionTable.grantReadWriteData(handlerRole);

    const handler = new PythonFunction(this, "Handler", {
      entry: path.join(__dirname, "../../backend"),
      index: "app/published_websocket.py",
      bundling: {
        assetExcludes: [...excludeDockerImage],
        buildArgs: { POETRY_VERSION: "1.8.3" },
      },
      runtime: Runtime.PYTHON_3_13,
      memorySize: 512,
      timeout: Duration.minutes(15),
      environment: {
        ACCOUNT: Stack.of(this).account,
        REGION: Stack.of(this).region,
        BEDROCK_REGION: props.bedrockRegion,
        CONVERSATION_TABLE_NAME: props.conversationTableName,
        BOT_TABLE_NAME: props.botTableName,
        TABLE_ACCESS_ROLE_ARN: props.tableAccessRoleArn,
        LARGE_MESSAGE_BUCKET: props.largeMessageBucketName,
        WEBSOCKET_SESSION_TABLE_NAME: sessionTable.tableName,
        ENABLE_BEDROCK_CROSS_REGION_INFERENCE:
          props.enableBedrockCrossRegionInference.toString(),
        BOT_ID: props.botId,
        API_KEY_PARAMETER_NAME: apiKeyParameter.parameterName,
      },
      role: handlerRole,
      snapStart: props.enableLambdaSnapStart
        ? SnapStartConf.ON_PUBLISHED_VERSIONS
        : undefined,
      logRetention: logs.RetentionDays.THREE_MONTHS,
    });

    const webSocketApi = new apigwv2.WebSocketApi(this, "WebSocketApi", {
      connectRouteOptions: {
        integration: new WebSocketLambdaIntegration(
          "ConnectIntegration",
          handler.currentVersion
        ),
      },
    });
    webSocketApi.addRoute("$default", {
      integration: new WebSocketLambdaIntegration(
        "DefaultIntegration",
        handler.currentVersion
      ),
    });
    new apigwv2.WebSocketStage(this, "WebSocketStage", {
      webSocketApi,
      stageName: this.defaultStageName,
      autoDeploy: true,
    });
    webSocketApi.grantManageConnections(handler);

    this.webSocketApi = webSocketApi;

    new CfnOutput(this, "WebSocketEndpoint", {
      value: `${this.webSocketApi.apiEndpoint}/${this.defaultStageName}`,
    });
  }
}
