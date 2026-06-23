package org.faultTree;


import org.faultTree.gate.ANDGate;
import org.faultTree.gate.Gate;
import org.faultTree.gate.KofNGate;
import org.faultTree.zdd.ZDD2;

import java.util.*;

public class StaticFaultTree extends FaultTree {
    private static final int MAX_MCS_SIZE = 5;
    private Map<ComponentNode, Double> discounts;
    private boolean useMOCUS;
    private final ZDD2 zdd;
    private final Map<ComponentNode, Integer> comp2var = new HashMap<>();
    private final Map<Integer, ComponentNode> var2comp = new HashMap<>();
    private int mcsZDD;

    public StaticFaultTree(Gate rootGate) {
        super(rootGate);
        this.discounts = new HashMap<>();
        this.useMOCUS = rootGate.estimateLogMCS() < Math.log10(50_000);
        int n = this.rootGate.getAllNodes().size();
        int extraNodes = 5000000;
        this.zdd = new ZDD2(n + extraNodes);

        for (ComponentNode c : this.rootGate.getAllNodes()) {
            int v = zdd.createVar();
            comp2var.put(c, v);
            var2comp.put(v, c);
        }
        this.mcsZDD = build(this.rootGate,0);
    }

    private final Map<Gate, Map<Integer, Integer>> buildCache = new HashMap<>();

    private int build(Gate g, int currentSize) {
        if (currentSize > MAX_MCS_SIZE) return zdd.empty();

        Map<Integer, Integer> bySize =
                buildCache.computeIfAbsent(g, k -> new HashMap<>());

        Integer cached = bySize.get(currentSize);
        if (cached != null) return cached;

        int result;

        if (g instanceof KofNGate k) {
            result = buildKofN(k, currentSize);
            bySize.put(currentSize, result);
            return result;
        }

        boolean isAnd = g instanceof ANDGate;
        List<Integer> parts = new ArrayList<>();

        // components
        for (ComponentNode c : g.getNodes()) {
            int newSize = currentSize + 1;
            if (newSize > MAX_MCS_SIZE) continue;
            int leaf = zdd.change(zdd.base(), comp2var.get(c));
            parts.add(leaf);
        }

        // sub gates
        for (Gate sub : g.getGates()) {
            int subZ = build(sub, currentSize);
            if (subZ != zdd.empty()) {
                parts.add(subZ);
            }
        }

        if (parts.isEmpty())
            result = isAnd ? zdd.base() : zdd.empty();
        else
            result = isAnd ? mulBalanced(parts) : unionBalanced(parts);

        bySize.put(currentSize, result);
        return result;
    }


    private int buildKofN(KofNGate k, int currentSize) {
        int K = k.getK();
        List<Integer> children = new ArrayList<>();

        for (ComponentNode c : k.getNodes())
            children.add(zdd.change(zdd.base(), comp2var.get(c)));

        for (Gate g : k.getGates()) {
            int sub = build(g, currentSize + 1);
            if (sub != zdd.empty()) children.add(sub);
        }

        if (K + currentSize > MAX_MCS_SIZE)
            return zdd.empty();

        List<Integer> terms = new ArrayList<>();
        kofnRec(children, K, 0, new ArrayList<>(), terms, currentSize);

        return terms.isEmpty() ? zdd.empty() : unionBalanced(terms);
    }

    private void kofnRec(List<Integer> list, int k, int i,
                         List<Integer> cur, List<Integer> out,
                         int currentSize) {

        if (cur.size() == k) {
            if (cur.size() + currentSize <= MAX_MCS_SIZE) {
                out.add(mulBalanced(new ArrayList<>(cur)));
            }
            return;
        }

        if (i >= list.size()) return;

        if (cur.size() + currentSize > MAX_MCS_SIZE) return;

        // include
        cur.add(list.get(i));
        kofnRec(list, k, i + 1, cur, out, currentSize);
        cur.remove(cur.size() - 1);

        // skip
        kofnRec(list, k, i + 1, cur, out, currentSize);
    }


    private int mulBalanced(List<Integer> nodes) {
        if (nodes.isEmpty()) return zdd.base();
        if (nodes.size() == 1) return nodes.get(0);

        int mid = nodes.size() / 2;
        int left = mulBalanced(nodes.subList(0, mid));
        int right = mulBalanced(nodes.subList(mid, nodes.size()));
        return zdd.mul(left, right);
    }


    private int unionBalanced(List<Integer> nodes) {
        if (nodes.isEmpty()) return zdd.empty();
        if (nodes.size() == 1) return nodes.get(0);
        int mid = nodes.size() / 2;
        int left = unionBalanced(nodes.subList(0, mid));
        int right = unionBalanced(nodes.subList(mid, nodes.size()));
        return zdd.union(left, right);
    }

    public static class StaticFaultTreeBuilder {
        private Gate root;

        public StaticFaultTreeBuilder(Gate root) {
            this.root = root;
        }

        public StaticFaultTreeBuilder addNode(ComponentNode node) {
            root.addNode(node);
            return this;
        }

        public StaticFaultTreeBuilder addGate(Gate gate) {
            root.addGate(gate);
            return this;
        }

        public StaticFaultTreeBuilder addFaultTree(StaticFaultTree faultTree) {
            root.addGate(faultTree.getRootGate());
            return this;
        }

        public StaticFaultTree build() {
            return new StaticFaultTree(root);
        }
    }
}
