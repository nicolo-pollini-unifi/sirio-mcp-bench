package org.system;

import java.util.ArrayList;
import java.util.List;


public class ComponentBasedSystem {
    List<FaultMode> faultModes;

    public ComponentBasedSystem() {
        faultModes = new ArrayList<FaultMode>();
    }

    public void addFaultMode(FaultMode mode) {
        faultModes.add(mode);
    }

    public List<FaultMode> getFaultModes() {
        return faultModes;
    }
}
