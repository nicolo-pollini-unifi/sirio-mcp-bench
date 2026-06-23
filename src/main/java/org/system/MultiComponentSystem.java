package org.system;


import org.faultTree.StaticFaultTree;
import org.oristool.petrinet.*;

import java.math.MathContext;
import java.util.HashMap;
import java.util.Map;


public class MultiComponentSystem {
    private StaticFaultTree faultTree;
    private PetriNet systemPetrinet;
    private Marking systemMarking;
    private String failureCondition;
    private MathContext MC;
    private Map<String, String> components;
    public static boolean debug = false;

    public MultiComponentSystem(StaticFaultTree faultTree) {
        this.faultTree = faultTree;
        this.systemPetrinet = new PetriNet();
        this.systemMarking = new Marking();
        this.components = new HashMap<>();
        this.failureCondition = "tallala";
        this.MC = new MathContext(50);
    }
}
