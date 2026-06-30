package org.swam.sirio_mcp_server;

import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.ai.tool.method.MethodToolCallbackProvider;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;

@SpringBootApplication
public class SirioMcpServerApplication {

    public static void main(String[] args) {
        SpringApplication.run(SirioMcpServerApplication.class, args);
    }

    @Bean
    public ToolCallbackProvider SIRIOTools(SirioService service) {
        return MethodToolCallbackProvider.builder().toolObjects(service).build();
    }

}
