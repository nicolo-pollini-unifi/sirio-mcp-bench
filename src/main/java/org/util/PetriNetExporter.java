package org.util;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import org.oristool.models.pn.PostUpdater;
import org.oristool.models.pn.Priority;
import org.oristool.models.stpn.trees.StochasticTransitionFeature;
import org.oristool.petrinet.*;

import java.lang.reflect.Field;
import java.util.*;

public class PetriNetExporter {

    public static String exportToJson(PetriNet petriNet, Marking marking) {
        Map<String, Object> graph = exportToMap(petriNet, marking);
        Gson gson = new GsonBuilder().setPrettyPrinting().create();
        return gson.toJson(graph);
    }

    public static Map<String, Object> exportToMap(PetriNet petriNet, Marking marking) {
        Map<String, Object> root = new LinkedHashMap<>();

        if (petriNet == null) {
            root.put("places", Collections.emptyList());
            root.put("transitions", Collections.emptyList());
            root.put("arcs", Collections.emptyList());
            return root;
        }

        // 1. Export Places
        List<Map<String, Object>> placesList = new ArrayList<>();
        for (Place p : petriNet.getPlaces()) {
            Map<String, Object> placeMap = new LinkedHashMap<>();
            String name = p.getName();
            int tokens = (marking != null) ? marking.getTokens(p) : 0;
            placeMap.put("name", name);
            placeMap.put("tokens", tokens);

            String nameLower = name.toLowerCase();
            boolean isTopFail = nameLower.contains("top") && nameLower.contains("fail")
                             && !nameLower.contains("armed")
                             && !nameLower.contains("work");
            placeMap.put("is_top_fail", isTopFail);
            placesList.add(placeMap);
        }
        root.put("places", placesList);

        // 2. Export Transitions
        List<Map<String, Object>> transitionsList = new ArrayList<>();
        for (Transition t : petriNet.getTransitions()) {
            Map<String, Object> transMap = new LinkedHashMap<>();
            transMap.put("name", t.getName());

            String type = "immediate";
            Double rate = null;
            int priority = 0;
            String enablingFunction = null;
            String postUpdater = null;

            StochasticTransitionFeature stf = t.getFeature(StochasticTransitionFeature.class);
            if (stf != null) {
                type = "exponential";
                rate = extractRate(stf);
            }

            Priority prioFeature = t.getFeature(Priority.class);
            if (prioFeature != null) {
                priority = extractPriority(prioFeature);
            }

            EnablingFunction efFeature = t.getFeature(EnablingFunction.class);
            if (efFeature != null) {
                enablingFunction = extractEnablingCondition(efFeature);
            }

            PostUpdater puFeature = t.getFeature(PostUpdater.class);
            if (puFeature != null) {
                postUpdater = extractPostUpdaterExpression(puFeature);
            }

            transMap.put("type", type);
            transMap.put("rate", rate);
            transMap.put("priority", priority);
            transMap.put("enabling_function", enablingFunction);
            transMap.put("post_updater", postUpdater);
            transitionsList.add(transMap);
        }
        root.put("transitions", transitionsList);

        // 3. Export Arcs
        List<Map<String, Object>> arcsList = new ArrayList<>();

        for (Transition t : petriNet.getTransitions()) {
            for (Precondition pre : petriNet.getPreconditions(t)) {
                Map<String, Object> arcMap = new LinkedHashMap<>();
                arcMap.put("from", pre.getPlace().getName());
                arcMap.put("to", t.getName());
                arcMap.put("type", "precondition");
                arcMap.put("weight", 1);
                arcsList.add(arcMap);
            }

            for (Postcondition post : petriNet.getPostconditions(t)) {
                Map<String, Object> arcMap = new LinkedHashMap<>();
                arcMap.put("from", t.getName());
                arcMap.put("to", post.getPlace().getName());
                arcMap.put("type", "postcondition");
                arcMap.put("weight", 1);
                arcsList.add(arcMap);
            }

            for (InhibitorArc inh : petriNet.getInhibitorArcs(t)) {
                Map<String, Object> arcMap = new LinkedHashMap<>();
                arcMap.put("from", inh.getPlace().getName());
                arcMap.put("to", t.getName());
                arcMap.put("type", "inhibitor");
                arcMap.put("weight", 1);
                arcsList.add(arcMap);
            }
        }
        root.put("arcs", arcsList);

        return root;
    }

    private static Double extractRate(StochasticTransitionFeature stf) {
        if (stf == null) return null;
        try {
            Object density = stf.density();
            if (density != null) {
                for (Field f : density.getClass().getDeclaredFields()) {
                    f.setAccessible(true);
                    Object val = f.get(density);
                    if ("rate".equalsIgnoreCase(f.getName()) && val instanceof Number) {
                        return ((Number) val).doubleValue();
                    }
                }
                for (Field f : density.getClass().getDeclaredFields()) {
                    f.setAccessible(true);
                    Object val = f.get(density);
                    if (val instanceof Number) {
                        return ((Number) val).doubleValue();
                    }
                }
            }
        } catch (Exception ignored) {}
        return 0.0;
    }

    private static int extractPriority(Priority prio) {
        if (prio == null) return 0;
        try {
            for (Field f : prio.getClass().getDeclaredFields()) {
                f.setAccessible(true);
                Object val = f.get(prio);
                if (val instanceof Number) {
                    return ((Number) val).intValue();
                }
            }
        } catch (Exception ignored) {}
        return 0;
    }

    private static String extractEnablingCondition(EnablingFunction ef) {
        if (ef == null) return null;
        try {
            for (Field f : ef.getClass().getDeclaredFields()) {
                f.setAccessible(true);
                Object val = f.get(ef);
                if (val instanceof String && !((String) val).isEmpty()) {
                    return (String) val;
                }
            }
        } catch (Exception ignored) {}
        return ef.toString();
    }

    private static String extractPostUpdaterExpression(PostUpdater pu) {
        if (pu == null) return null;
        try {
            for (Field f : pu.getClass().getDeclaredFields()) {
                f.setAccessible(true);
                Object val = f.get(pu);
                if (val instanceof String && !((String) val).isEmpty()) {
                    return (String) val;
                }
            }
        } catch (Exception ignored) {}
        return pu.toString();
    }
}
