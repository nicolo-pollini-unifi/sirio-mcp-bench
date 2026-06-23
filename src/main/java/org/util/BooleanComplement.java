package org.util;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class BooleanComplement {

    private static boolean isJavaKeyword(String word) {
        return Set.of(
                "if", "else", "while", "for", "return", "true", "false", "null"
        ).contains(word);
    }

    public static String complementExpression(String expression) {
        String[] expressions = expression.split("\\s*;\\s*");

        // Regex patterns
        Pattern varPattern = Pattern.compile("\\b[a-zA-Z_][a-zA-Z0-9_]*\\b");
        Pattern opPattern = Pattern.compile(">=|<=|==|!=|>|<");

        List<String> processed = new ArrayList<>();
        Set<String> variables = new HashSet<>();

        for (String expr : expressions) {
            if (expr.isEmpty()) continue;

            // Step 2: Find variables
            Matcher varMatcher = varPattern.matcher(expr);
            while (varMatcher.find()) {
                String var = varMatcher.group();
                if (!isJavaKeyword(var)) {
                    variables.add(var);
                }
            }

            // Step 3: Replace comparison operators with their complements
            String replacedExpr = opPattern.matcher(expr).replaceAll(match -> {
                switch (match.group()) {
                    case ">": return "<=";
                    case "<": return ">=";
                    case ">=": return "<";
                    case "<=": return ">";
                    case "==": return "!=";
                    case "!=": return "==";
                    default: return match.group();
                }
            });

            processed.add(replacedExpr.trim());
        }

        // Output processed expressions
        StringBuilder complementBuilder =  new StringBuilder();
        for (String expr : processed) {
            complementBuilder.append(" ; ");
            if(complementBuilder.toString().equals(" ; ")){
                complementBuilder = new StringBuilder(expr);
            }else{
                complementBuilder.append(expr);
            }
        }
        return complementBuilder.toString();
    }

    public static void main(String[] args) {
        String input = "p1 + p2 + p3 >0 ; failure > 6; p2 < 0; p6 >= 0 ; p1 + ( p2 * p3 ) > 0 ; p1 == 0 ; p2 != 5 ;";
        System.out.println(complementExpression(input));
    }

}