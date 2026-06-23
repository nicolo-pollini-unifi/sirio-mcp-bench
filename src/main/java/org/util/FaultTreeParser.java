package org.util;

import org.faultTree.ComponentNode;
import org.faultTree.gate.ANDGate;
import org.faultTree.gate.Gate;
import org.faultTree.gate.KofNGate;
import org.faultTree.gate.ORGate;

import java.util.*;

/**
 * Parser for Boolean logic expressions representing Fault Trees.
 * Supports AND (&), OR (|), and KofN (KOFN(k, ...)) gates.
 */
public class FaultTreeParser {

    private final String input;
    private final Map<String, ComponentNode> registry;
    private int pos = 0;
    private int gateCount = 0;

    private FaultTreeParser(String input, Map<String, ComponentNode> registry) {
        this.input = input.replace(" ", "");
        this.registry = registry;
    }

    /**
     * Parses a boolean expression and returns the root Gate of the Fault Tree.
     *
     * @param expression The boolean expression (e.g., "(A & B) | KOFN(2, C, D, E)")
     * @param registry   A map of component identifiers to ComponentNode objects.
     * @return The root Gate of the constructed tree.
     */
    public static Gate parse(String expression, Map<String, ComponentNode> registry) {
        Object result = new FaultTreeParser(expression, registry).parseExpression();
        if (result instanceof Gate) {
            return (Gate) result;
        } else {
            ComponentNode comp = (ComponentNode) result;
            ORGate rootWrap = new ORGate("root_leaf_" + comp.getName());
            rootWrap.addNode(comp);
            return rootWrap;
        }
    }

    private Object parseExpression() {
        Object node = parseTerm();
        while (match('|')) {
            Object right = parseTerm();
            if (node instanceof ORGate && ((ORGate) node).getIdentifier().startsWith("auto_OR_")) {
                addToGate((ORGate) node, right);
            } else {
                ORGate or = new ORGate("auto_OR_" + (++gateCount));
                addToGate(or, node);
                addToGate(or, right);
                node = or;
            }
        }
        return node;
    }

    private Object parseTerm() {
        Object node = parseFactor();
        while (match('&')) {
            Object right = parseFactor();
            if (node instanceof ANDGate && ((ANDGate) node).getIdentifier().startsWith("auto_AND_")) {
                addToGate((ANDGate) node, right);
            } else {
                ANDGate and = new ANDGate("auto_AND_" + (++gateCount));
                addToGate(and, node);
                addToGate(and, right);
                node = and;
            }
        }
        return node;
    }

    private Object parseFactor() {
        if (match('(')) {
            Object node = parseExpression();
            expect(')');
            return node;
        } else if (lookAhead("KOFN(")) {
            return parseKofN();
        } else {
            String id = parseIdentifier();
            ComponentNode comp = registry.get(id);
            if (comp == null) {
                throw new RuntimeException("Component not found in registry: " + id);
            }
            return comp;
        }
    }

    private Gate parseKofN() {
        expect("KOFN(");
        int k = Integer.parseInt(parseIdentifier());
        expect(',');
        KofNGate kofn = new KofNGate("auto_KOFN_" + (++gateCount), k);

        do {
            addToGate(kofn, parseFactor());
        } while (match(','));

        expect(')');
        return kofn;
    }

    /**
     * Adds an operand (Gate or ComponentNode) to the target Gate.
     *
     * @param target The Gate to add the child to.
     * @param child  The child object (expected to be Gate or ComponentNode).
     */
    private void addToGate(Gate target, Object child) {
        if (child instanceof Gate) {
            target.addGate((Gate) child);
        } else if (child instanceof ComponentNode) {
            target.addNode((ComponentNode) child);
        } else {
            throw new IllegalArgumentException("Unsupported child type: " + child.getClass().getName());
        }
    }

    private String parseIdentifier() {
        StringBuilder sb = new StringBuilder();
        while (pos < input.length() && (Character.isLetterOrDigit(peek()) || peek() == '_')) {
            sb.append(input.charAt(pos++));
        }
        return sb.toString();
    }

    private boolean match(char c) {
        if (pos < input.length() && input.charAt(pos) == c) {
            pos++;
            return true;
        }
        return false;
    }

    private void expect(char c) {
        if (!match(c)) {
            throw new RuntimeException("Expected '" + c + "' at position " + pos);
        }
    }

    private void expect(String s) {
        for (char c : s.toCharArray()) {
            expect(c);
        }
    }

    private boolean lookAhead(String s) {
        if (pos + s.length() > input.length()) return false;
        return input.substring(pos, pos + s.length()).equalsIgnoreCase(s);
    }

    private char peek() {
        if (pos >= input.length()) return '\0';
        return input.charAt(pos);
    }
}
