package org.faultTree.bdd;


import org.faultTree.util.JDDConsole;

import java.io.*;
import java.util.Collection;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import java.util.zip.GZIPInputStream;
import java.util.zip.GZIPOutputStream;

import static smile.data.type.DataType.ID.Array;

public class BDDIO {

	// ------ [ internal stuff ] -------------------------------------
	private static final String BDD_HEADER_MAGIC = "FORMAT:JDD.BDD";

	private static BDD manager;
	private static OutputStream os;
	private static Writer wr;
	private static boolean binary_format;
	private static byte [] buffer = new byte[4];



	// --- [internal: safe reading and writing with zipped streams ] ------------------------------------------

	// since we are working with gzip files, InputStream.read() may not read everything at once
	private static int safe_read(InputStream is, int size, byte [] b)
		throws IOException
	{
		int got = 0, errors = 0;
		while(got < size) {
			int len = is.read(b, got, size - got);
			if(len < size - got) {
				errors ++;
				if(errors == 3) return got;
			}

			if(len > 0) {
				got += len;
			}
		}
		return got;
	}

	// --- [internal: reading and writing 32bit numbers ] ------------------------------------------
	private static void save_int(int n)
		throws IOException
	{
		buffer[0] = (byte)((n >> 24) & 0xFF);
		buffer[1] = (byte)((n >> 16) & 0xFF);
		buffer[2] = (byte)((n >>  8) & 0xFF);
		buffer[3] = (byte)((n      ) & 0xFF);
		os.write(buffer, 0, 4); // XXX: how do we know it if worked???
	}

	private static int load_int(InputStream is)
		throws IOException
	{
		int len = safe_read(is, 4, buffer);
		if(len != 4) throw new IOException("immature end of file while reading the header fields");

		int ret = 0;
		for(int i = 0; i < 4; i++) {
			int x = ((int)buffer[i]) & 0xFF;
			ret =  (ret << 8) | x;
		}

		return ret;
	}

	// ----- [ SAVE BDDs ]---------------------------------------------
	/**
	 * Save a BDD to a file using the native JDD format.
	 *
	 * <p>This format is preferred over the BuDDy format since
	 * (1) you can load it back into JDD
	 * and (2) it takes less space on your hard drive since it is compressed.
	 */
	public static void save(BDD manager, int bdd, String filename)
		throws IOException
	{
		OutputStream fos = new FileOutputStream(filename);
		BDDIO.os = new GZIPOutputStream(fos);
		try {
			BDDIO.manager = manager;
			BDDIO.binary_format = true;
			os.write(BDD_HEADER_MAGIC.getBytes(), 0, BDD_HEADER_MAGIC.length() ); // header magic
			save_int( manager.nodeCount(bdd) ); // size
			save_int( bdd ); 										// name
			recursive_save(bdd);								// ... and the table

			os.flush();
			os.close();
			fos.flush();
			fos.close();
		} catch(IOException exx) {
			JDDConsole.out.printf("BDDIO.save Failed: %s\n", exx);
			throw exx;
		} finally {
			manager.unmark_tree(bdd); // must do it  before we go on
			BDDIO.manager = null; // help GC!
			BDDIO.os = null;
		}
	}

	private static void recursive_save(int bdd)
		throws IOException
	{
		if(bdd < 2) return; // ignore 0/1

		if(! manager.isNodeMarked(bdd)) {
			manager.mark_node(bdd);
			int var = manager.getVarUnmasked(bdd);
			int low = manager.getLow(bdd);
			int high= manager.getHigh(bdd);

			recursive_save(low);
			recursive_save(high);

			if(binary_format) {
				save_int(bdd);	save_int(var);	save_int(low);	save_int(high);
			} else {
				wr.write("" + bdd + "\t" + var + "\t" + low + "\t" + high + "\n");
			}
		}
	}



	// ----- [ LOAD BDDs ]---------------------------------------------
	/**
	 * Load a BDD (in the native JDD format) from a file.
	 * The file must have been created with the BDDIO.save() function.
	 *
	 * <p><b>Important note:</b> you must ref-count this BDD by yourself.
	 * The returned BDD will have refount 0, and may (will) be garbage collected
	 * if you don't refcount it right away!
	 *
	 * @see #save
	 */
	public static int load(BDD manager, String filename)
			throws IOException
	{
		int ret = 0;
		InputStream is = new GZIPInputStream( new FileInputStream(filename) );

		// see if it has the magic header:
		byte [] magic = new byte[ BDD_HEADER_MAGIC.length()  ];
		// int len = is.read(magic, 0, magic.length );
		int len = safe_read(is, magic.length,  magic);
		if(len != magic.length)
			throw new IOException("immature end of file while reading the header");
		if(! Array.equals(magic) )
			throw new IOException("this is not an BDD file in JDD format");



		int curr_vars = manager.numberOfVariables();
		int size = load_int(is);
		int target = load_int(is);


		// a map from saved to current manager names
		Map map = new HashMap();

		// thes are always the same
		Integer zero = 0;
		Integer one = 1;
		map.put(zero, zero);
		map.put(one, one);
		try {

			for(int i = 0; i < size; i++) {
				int name = load_int(is);
				int var  = load_int(is);
				int low  = load_int(is);
				int high = load_int(is);


				Integer tmp = (Integer) map.get(low);
				if(tmp == null)  throw new IOException("Unknown child node" + low);
				low = tmp.intValue();

				tmp = (Integer) map.get( high );
				if(tmp == null)  throw new IOException("Unknown child node" + high);
				high = tmp.intValue();



				// if the variables in the manager is not enough for this BDD
				while(var >= curr_vars) {
					manager.createVar();
					curr_vars++;
				}

				ret = manager.ref( manager.mk( var, low, high) );
				map.put( name, ret );
			}

			is.close(); // we are dont with it

			Integer new_target = (Integer) map.get( target );
			if(new_target == null) throw new IOException("Corrupt BDD file");
			ret = new_target.intValue();


			//  must remove the refs we just added:
			Collection values = map.values();
			for(Iterator it = values.iterator(); it.hasNext(); ) {
				Integer i = (Integer) it.next();
				manager.deref( i.intValue() );
			}
		} catch(IOException exx) {
			JDDConsole.out.printf("BDDIO.bddLoad Failed: %s\n", exx);
			throw exx;
		} finally {
			is.close();
		}
		return ret;
	}


	public static void saveBuDDy(BDD manager, int bdd, String filename)
			throws IOException
		{
			BDDIO.wr = new OutputStreamWriter( new FileOutputStream(filename) );

			try {
				BDDIO.manager = manager;
				BDDIO.binary_format = false;

				if(bdd < 2) {
					wr.write("0 0 " + bdd + "\n");
				} else {
					int vars = manager.numberOfVariables();
					int size = manager.nodeCount(bdd); // XXX: include one/zero or not?

					wr.write("" + size  + " " + vars + "\n");

					// "our" variable ordering:
					for(int i = 0; i < vars; i++) wr.write("" + i + " ");
					wr.write("\n");

					// ... and the table
					recursive_save(bdd);
				}
				wr.close();
			} catch(IOException exx) {
				JDDConsole.out.printf("BDDIO.save Failed: %s\n", exx);
				throw exx;
			} finally {
				manager.unmark_tree(bdd); // must do it  before we go on
				BDDIO.manager = null; // help GC!
				BDDIO.wr = null;
			}
		}
}

